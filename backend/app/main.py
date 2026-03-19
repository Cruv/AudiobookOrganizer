import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Configure logging so scan messages appear in Docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.user import User, UserSession  # noqa: E402
from app.routers import auth, books, organize, scans  # noqa: E402
from app.routers import settings as settings_router  # noqa: E402


def _run_migrations(engine_instance):
    """Run lightweight schema migrations for existing databases.

    SQLAlchemy create_all only creates NEW tables, not new columns on
    existing tables.  This adds any missing columns via ALTER TABLE.
    """
    import sqlalchemy as sa

    migrations = [
        # (table, column, col_type_sql)
        ("books", "edition", "TEXT"),
        ("scans", "status_detail", "TEXT"),
    ]

    with engine_instance.connect() as conn:
        for table, column, col_type in migrations:
            # Check if column already exists
            result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
            existing_cols = {row[1] for row in result}
            if column not in existing_cols:
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                logging.getLogger(__name__).info("Migration: added %s.%s", table, column)
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield


app = FastAPI(
    title="Audiobook Organizer",
    description="Organize audiobooks into Chaptarr-compatible folder structures",
    version="1.0.9",
    lifespan=lifespan,
)

# CORS for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — protects /api/* except /api/health and /api/auth/*
AUTH_EXEMPT = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/register"}

# Cached flag: once users exist, we always require auth.
# Set to True on first user registration; avoids querying User table on every request.
_has_users_cache: bool | None = None


def invalidate_has_users_cache() -> None:
    """Call after first user registration to flip the cache."""
    global _has_users_cache
    _has_users_cache = True


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    global _has_users_cache
    path = request.url.path
    # Only protect /api/* routes
    if path.startswith("/api/") and path not in AUTH_EXEMPT:
        db = SessionLocal()
        try:
            # Check cached flag; only query DB if unknown
            if _has_users_cache is None:
                _has_users_cache = db.query(User).first() is not None
            if _has_users_cache:
                token = request.cookies.get("session_token")
                if not token:
                    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
                session = (
                    db.query(UserSession)
                    .filter(
                        UserSession.token == token,
                        UserSession.expires_at > datetime.now(timezone.utc),
                    )
                    .first()
                )
                if not session:
                    return JSONResponse(status_code=401, content={"detail": "Session expired"})
        finally:
            db.close()
    return await call_next(request)


# API routes
app.include_router(auth.router)
app.include_router(scans.router)
app.include_router(scans.browse_router)
app.include_router(books.router)
app.include_router(organize.router)
app.include_router(organize.purge_router)
app.include_router(settings_router.router)


@app.get("/api/health")
def health_check():
    import sqlalchemy as sa
    try:
        db = SessionLocal()
        db.execute(sa.text("SELECT 1"))
        db.close()
        return {"status": "ok", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable"},
        )


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
