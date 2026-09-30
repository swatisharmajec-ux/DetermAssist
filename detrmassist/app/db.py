"""
DB session setup. SQLite by default for local dev — swap DATABASE_URL for
Postgres once real volume shows up (models.py uses String(36) for ids
specifically so this swap doesn't require a schema rewrite; Postgres's
native UUID type is a drop-in upgrade, not a redesign).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
