from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    mark_price REAL NOT NULL,
    index_price REAL NOT NULL,
    best_bid REAL NOT NULL,
    best_ask REAL NOT NULL,
    spread REAL NOT NULL,
    spread_bps REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orderbook_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES market_snapshots(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK(side IN ('bid', 'ask')),
    price REAL NOT NULL,
    size REAL NOT NULL,
    notional REAL NOT NULL,
    level_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS funding_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    rate REAL NOT NULL,
    next_funding_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_market_status (
    exchange_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_collection_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (exchange_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_lookup
ON market_snapshots(exchange_id, symbol, timestamp);

CREATE INDEX IF NOT EXISTS idx_orderbook_snapshot
ON orderbook_levels(snapshot_id, side, level_index);

CREATE INDEX IF NOT EXISTS idx_funding_lookup
ON funding_rates(exchange_id, symbol, timestamp);
"""


class AsyncSQLite:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        def _connect() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

        self._conn = await asyncio.to_thread(_connect)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def initialize(self) -> None:
        await self.executescript(SCHEMA)

    async def executescript(self, script: str) -> None:
        async with self._lock:
            conn = self._require_conn()
            await asyncio.to_thread(conn.executescript, script)
            await asyncio.to_thread(conn.commit)

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        async with self._lock:
            conn = self._require_conn()
            cursor = await asyncio.to_thread(conn.execute, sql, tuple(params))
            await asyncio.to_thread(conn.commit)
            return cursor

    async def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> None:
        async with self._lock:
            conn = self._require_conn()
            await asyncio.to_thread(conn.executemany, sql, [tuple(row) for row in params])
            await asyncio.to_thread(conn.commit)

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        async with self._lock:
            conn = self._require_conn()
            cursor = await asyncio.to_thread(conn.execute, sql, tuple(params))
            return await asyncio.to_thread(cursor.fetchall)

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def __aenter__(self) -> "AsyncSQLite":
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()
