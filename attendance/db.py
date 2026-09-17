from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path(os.environ.get("ATTENDANCE_DB", Path.home() / ".attendance-tracker" / "attendance.db"))


def get_engine(db_path: str | Path = DEFAULT_DB_PATH):
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(db_path: str | Path = DEFAULT_DB_PATH) -> sessionmaker[Session]:
    engine = get_engine(db_path)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
