from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import settings


# This engine is used by workers and API handlers to update document states.
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
