"""Cache SQLite đơn giản để không tra lại cùng một mã vận đơn liên tục."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


class TrackingCache:
    def __init__(self, path: str = ".spx_cache.sqlite3", ttl_seconds: int = 30 * 60):
        self.ttl = ttl_seconds
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS tracking ("
            " tn TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at REAL NOT NULL)"
        )
        self._db.commit()

    def get(self, tn: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT payload, fetched_at FROM tracking WHERE tn = ?", (tn,)
        ).fetchone()
        if row is None or time.time() - row[1] > self.ttl:
            return None
        return json.loads(row[0])

    def set(self, tn: str, payload: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO tracking (tn, payload, fetched_at) VALUES (?, ?, ?)",
            (tn, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
