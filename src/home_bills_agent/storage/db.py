"""Работа с базой данных SQLite."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from home_bills_agent.storage.models import Base

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "billing.db"


def init_db(db_path: str | Path | None = None) -> sessionmaker:
    """Инициализировать движок SQLite и создать таблицы.

    Принимает либо путь к файлу, либо SQLAlchemy URL вида sqlite:///путь.
    Возвращает sessionmaker для создания сессий.
    """
    if isinstance(db_path, str) and db_path.startswith("sqlite:///"):
        path = Path(db_path[len("sqlite:///"):])
    else:
        path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{path}", echo=False, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(session_factory: sessionmaker) -> Session:
    """Создать новую сессию."""
    return session_factory()