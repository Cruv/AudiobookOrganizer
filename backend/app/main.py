import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Configure logging so scan messages appear in Docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

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

    SQLAlchemy create_all only creates NEW tables, not new columns or
    indexes on existing tables. This adds any missing columns via ALTER
    TABLE and creates any missing indexes.
    """
    import sqlalchemy as sa

    migrations = [
        # (table, column, col_type_sql)
        ("books", "edition", "TEXT"),
        ("books", "lookup_error", "TEXT"),
        ("scans", "status_detail", "TEXT"),
    ]

    indexes = [
        # (name, create_sql)
        (
            "uq_scanned_folder_scan_path",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scanned_folder_scan_path "
            "ON scanned_folders (scan_id, folder_path)",
        ),
        (
            "ix_scanned_folders_folder_path",
            "CREATE INDEX IF NOT EXISTS ix_scanned_folders_folder_path "
            "ON scanned_folders (folder_path)",
        ),
        (
            "ix_books_confidence",
            "CREATE INDEX IF NOT EXISTS ix_books_confidence ON books (confidence)",
        ),
    ]

    with engine_instance.connect() as conn:
        for table, column, col_type in migrations:
            result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
            existing_cols = {row[1] for row in result}
            if column not in existing_cols:
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                logger.info("Migration: added %s.%s", table, column)
        for _, ddl in indexes:
            conn.execute(sa.text(ddl))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield


APP_VERSION = "1.7.0"

app = FastAPI(
    title="Audiobook Organizer",
    description="Organize audiobooks into Chaptarr-compatible folder structures",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Detect production: static dir exists = running in Docker behind nginx
_is_production = os.path.isdir(os.path.join(os.path.dirname(__file__), "..", "static"))

# CORS — restrictive in production, permissive in dev
if _is_production:
    # In production, nginx serves everything on the same origin — no CORS needed.
    # Only allow the configured origins as a safety net.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Cookie"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# --------------------------------------------------------------------------- #
# Auth middleware — DEFAULT-DENY for /api/* with explicit exemptions
# --------------------------------------------------------------------------- #
# Huntarr lesson: keep the exempt list MINIMAL and use exact-match only.
# Never use substring or endswith matching for auth bypass.
AUTH_EXEMPT = frozenset({
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/register",
})

# Cached flag: once users exist, we always require auth.
_has_users_cache: bool | None = None


def invalidate_has_users_cache() -> None:
    """Call after first user registration to flip the cache."""
    global _has_users_cache
    _has_users_cache = True


# --------------------------------------------------------------------------- #
# Global API rate limiter (Huntarr had none)
# --------------------------------------------------------------------------- #
_api_requests: dict[str, list[float]] = {}
API_RATE_LIMIT = 120  # requests per window
API_RATE_WINDOW = 60  # seconds


def _get_client_ip(request: Request) -> str:
    """Get real client IP, safely trusting X-Real-IP only from local nginx."""
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        # Behind nginx — trust X-Real-IP set from $remote_addr
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def _check_api_rate_limit(client_ip: str) -> bool:
    """Return True if request should be allowed."""
    now = time.monotonic()
    attempts = _api_requests.get(client_ip, [])
    attempts = [t for t in attempts if now - t < API_RATE_WINDOW]
    _api_requests[client_ip] = attempts
    if len(attempts) >= API_RATE_LIMIT:
        return False
    attempts.append(now)
    return True


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    global _has_users_cache
    path = request.url.path

    # Only protect /api/* routes (static files, health check etc. pass through)
    if path.startswith("/api/"):
        # Rate limit all API endpoints
        client_ip = _get_client_ip(request)
        if not _check_api_rate_limit(client_ip):
            logger.warning("Rate limit exceeded for %s on %s", client_ip, path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
            )

        # Auth check for non-exempt paths
        if path not in AUTH_EXEMPT:
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
                    # Attach user info to request state for downstream handlers
                    request.state.user_id = session.user_id
                    request.state.session_token = session.token
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
        return {"status": "ok", "database": "connected", "version": APP_VERSION}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable"},
        )


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
