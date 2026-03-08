import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Configure logging so scan messages appear in Docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import books, organize, scans, settings as settings_router


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

# API routes
app.include_router(scans.router)
app.include_router(scans.browse_router)
app.include_router(books.router)
app.include_router(organize.router)
app.include_router(organize.purge_router)
app.include_router(settings_router.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
