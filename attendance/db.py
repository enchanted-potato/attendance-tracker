from __future__ import annotations

import os
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path(os.environ.get("ATTENDANCE_DB", Path.home() / ".attendance-tracker" / "attendance.db"))


def get_engine(db_path: str | Path = DEFAULT_DB_PATH):
    """Create a SQLAlchemy engine for the SQLite database, creating tables
    and parent directories as needed.

    :param db_path: filesystem path to the SQLite file, or ``":memory:"``
        for an in-memory database.
    :type db_path: str | pathlib.Path
    :returns: a connected engine with the schema already applied.
    :rtype: sqlalchemy.Engine
    """
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Opening database at {}", db_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(db_path: str | Path = DEFAULT_DB_PATH) -> sessionmaker[Session]:
    """Build a session factory bound to the SQLite database.

    :param db_path: filesystem path to the SQLite file, or ``":memory:"``
        for an in-memory database.
    :type db_path: str | pathlib.Path
    :returns: a ``sessionmaker`` that produces new sessions on call.
    :rtype: sqlalchemy.orm.sessionmaker
    """
    engine = get_engine(db_path)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
