"""Small, serialized SQLite persistence layer for a single controller."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class ControllerStorage:
    def __init__(self, database_path: Path, migration_dir: Path) -> None:
        self.database_path = database_path
        self.migration_dir = migration_dir
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(database_path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self.apply_migrations()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def apply_migrations(self) -> None:
        with self._lock:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            applied = {
                row[0]
                for row in self._connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for migration in sorted(self.migration_dir.glob("*.sql")):
                if migration.name in applied:
                    continue
                script = migration.read_text(encoding="utf-8")
                try:
                    self._connection.executescript(script)
                    self._connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (migration.name, time.time()),
                    )
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise

    def execute(
        self, sql: str, parameters: Iterable[Any] = (), *, commit: bool = True
    ) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._connection.execute(sql, tuple(parameters))
            if commit:
                self._connection.commit()
            return cursor

    def executemany(
        self, sql: str, parameters: Iterable[Iterable[Any]], *, commit: bool = True
    ) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._connection.executemany(sql, parameters)
            if commit:
                self._connection.commit()
            return cursor

    def fetchone(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, tuple(parameters)).fetchone()

    def fetchall(self, sql: str, parameters: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, tuple(parameters)).fetchall()

    def transaction(self):
        return _StorageTransaction(self)


class _StorageTransaction:
    def __init__(self, storage: ControllerStorage) -> None:
        self.storage = storage

    def __enter__(self) -> sqlite3.Connection:
        self.storage._lock.acquire()
        self.storage._connection.execute("BEGIN IMMEDIATE")
        return self.storage._connection

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is None:
                self.storage._connection.execute("COMMIT")
            else:
                self.storage._connection.execute("ROLLBACK")
        finally:
            self.storage._lock.release()


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
