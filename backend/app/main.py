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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Base
from app.models.user import User, UserSession
from app.routers import auth, books, organize, scans, settings as settings_router


def _run_migrations(engine_instance):
    """Run lightweight schema migrations for existing databases.

    SQLAlchemy create_all only creates NEW tables, not new columns on
    existing tables.  This adds any missing columns via ALTER TABLE.
    """
    import sqlalchemy as sa

    migrations = [
        # (table, column, col_type_sql)
        ("books", "edition", "TEXT"),
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
    version="0.1.0",
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


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Only protect /api/* routes
    if path.startswith("/api/") and path not in AUTH_EXEMPT:
        db = SessionLocal()
        try:
            has_users = db.query(User).first() is not None
            if has_users:
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
