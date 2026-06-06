import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings

# Ensure data directory exists
db_path = settings.database_url.replace("sqlite:///", "")
os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

# SQLite ignores foreign-key constraints unless they're enabled per
# connection. Without this every ondelete="CASCADE" in the models is a
# no-op, so deleting a parent (e.g. a Scan) would orphan its children at
# the DB level. Enable enforcement on each new connection.
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
