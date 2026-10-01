"""Create database resources lazily; imports require neither credentials nor a server."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import get_settings


@lru_cache
def get_engine():
    return create_engine(get_settings().require_database_url(), pool_pre_ping=True)


@lru_cache
def get_session_factory():
    return sessionmaker(autoflush=False, bind=get_engine())


def get_db():
    with get_session_factory()() as session:
        yield session
