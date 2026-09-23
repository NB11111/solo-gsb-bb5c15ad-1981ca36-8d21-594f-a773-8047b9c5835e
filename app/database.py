"""SQLite 访问层：连接管理、建表与题库初始化。"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable

from .config import settings
from .seed import SEED_ITEMS

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    stem          TEXT NOT NULL,
    options_json  TEXT NOT NULL,
    answer_index  INTEGER NOT NULL,
    a             REAL NOT NULL,
    b             REAL NOT NULL,
    exposure      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY,
    theta             REAL NOT NULL,
    current_item_id   TEXT REFERENCES items(id),
    answered_count    INTEGER NOT NULL DEFAULT 0,
    max_items         INTEGER NOT NULL,
    exposure_cap      INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'in_progress',
    finish_reason     TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    id                TEXT NOT NULL,
    session_id        TEXT NOT NULL REFERENCES sessions(id),
    item_id           TEXT NOT NULL REFERENCES items(id),
    selected_index    INTEGER NOT NULL,
    answer_index      INTEGER NOT NULL,
    score             INTEGER NOT NULL,
    probability       REAL NOT NULL,
    theta_before      REAL NOT NULL,
    theta_after       REAL NOT NULL,
    result_json       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    PRIMARY KEY (session_id, id)
);
"""


def get_db_path() -> str:
    return settings.db_path


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """每个请求一个连接；显式 BEGIN IMMEDIATE 控制写事务。"""
    conn = sqlite3.connect(
        db_path or get_db_path(),
        timeout=30.0,
        isolation_level=None,  # autocommit 模式，事务由代码显式管理
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: str | None = None, items: Iterable[dict[str, Any]] = SEED_ITEMS) -> None:
    """建库建表并写入初始题库（已存在的题目保留其曝光次数，不重置）。"""
    path = db_path or get_db_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)

    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        with conn:
            conn.executemany(
                """
                INSERT INTO items (id, stem, options_json, answer_index, a, b, exposure)
                VALUES (:id, :stem, :options_json, :answer_index, :a, :b, 0)
                ON CONFLICT(id) DO UPDATE SET
                    stem=excluded.stem,
                    options_json=excluded.options_json,
                    answer_index=excluded.answer_index,
                    a=excluded.a,
                    b=excluded.b
                """,
                list(items),
            )
    finally:
        conn.close()
