from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import DEFAULT_AVERAGE_WINDOWS, MARKET_RETENTION_DAYS
from .db import AsyncSQLite
from .models import (
    AverageFundingRate,
    AverageSpread,
    BookSide,
    CollectorMarketStatus,
    FundingRate,
    MarketSnapshot,
    OrderBookLevel,
    from_iso,
    to_iso,
)


class MarketDataRepository:
    def __init__(self, db: AsyncSQLite) -> None:
        self.db = db

    async def save_snapshot(self, snapshot: MarketSnapshot) -> int:
        cursor = await self.db.execute(
            """
            INSERT INTO market_snapshots (
                exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.exchange_id,
                snapshot.symbol,
                to_iso(snapshot.timestamp),
                snapshot.mark_price,
                snapshot.index_price,
                snapshot.best_bid,
                snapshot.best_ask,
                snapshot.spread,
                snapshot.spread_bps,
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        await self.db.executemany(
            """
            INSERT INTO orderbook_levels (
                snapshot_id, side, price, size, notional, level_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    snapshot_id,
                    level.side.value,
                    level.price,
                    level.size,
                    level.notional,
                    level.level_index,
                )
                for level in (*snapshot.bids, *snapshot.asks)
            ),
        )
        return snapshot_id

    async def save_funding_rate(self, funding: FundingRate) -> int:
        cursor = await self.db.execute(
            """
            INSERT INTO funding_rates (
                exchange_id, symbol, timestamp, rate, next_funding_time
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                funding.exchange_id,
                funding.symbol,
                to_iso(funding.timestamp),
                funding.rate,
                to_iso(funding.next_funding_time),
            ),
        )
        return int(cursor.lastrowid)

    async def save_funding_rate_if_new(self, funding: FundingRate) -> int | None:
        existing = await self.db.fetch_one(
            """
            SELECT id FROM funding_rates
            WHERE exchange_id = ? AND symbol = ? AND timestamp = ?
            LIMIT 1
            """,
            (
                funding.exchange_id,
                funding.symbol,
                to_iso(funding.timestamp),
            ),
        )
        if existing is not None:
            return None
        return await self.save_funding_rate(funding)

    async def latest_snapshot(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
    ) -> MarketSnapshot | None:
        where, params = self._filters(exchange_id, symbol)
        row = await self.db.fetch_one(
            f"""
            SELECT * FROM market_snapshots
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        if row is None:
            return None
        return await self._hydrate_snapshot(int(row["id"]))

    async def latest_orderbook(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
    ) -> tuple[MarketSnapshot, tuple[OrderBookLevel, ...], tuple[OrderBookLevel, ...]] | None:
        snapshot = await self.latest_snapshot(exchange_id, symbol)
        if snapshot is None:
            return None
        return snapshot, snapshot.bids, snapshot.asks

    async def average_spreads(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
        now: datetime | None = None,
    ) -> list[AverageSpread]:
        current_time = now or await self._latest_timestamp(exchange_id, symbol)
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        results: list[AverageSpread] = []
        base_where, base_params = self._filters(exchange_id, symbol)
        for label, seconds in DEFAULT_AVERAGE_WINDOWS.items():
            since = current_time - timedelta(seconds=seconds)
            if base_where:
                where = f"{base_where} AND timestamp >= ?"
                params = (*base_params, to_iso(since))
            else:
                where = "WHERE timestamp >= ?"
                params = (to_iso(since),)
            row = await self.db.fetch_one(
                f"""
                SELECT
                    AVG(spread) AS avg_spread,
                    AVG(spread_bps) AS avg_spread_bps,
                    COUNT(*) AS samples
                FROM market_snapshots
                {where}
                """,
                params,
            )
            samples = int(row["samples"] or 0) if row is not None else 0
            results.append(
                AverageSpread(
                    window=label,
                    avg_spread=None if samples == 0 else float(row["avg_spread"]),
                    avg_spread_bps=None if samples == 0 else float(row["avg_spread_bps"]),
                    samples=samples,
                )
            )
        return results

    async def _latest_timestamp(
        self,
        exchange_id: str | None,
        symbol: str | None,
    ) -> datetime | None:
        where, params = self._filters(exchange_id, symbol)
        row = await self.db.fetch_one(
            f"""
            SELECT timestamp FROM market_snapshots
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return None if row is None else from_iso(row["timestamp"])

    async def funding_history(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
        limit: int = 24,
    ) -> list[FundingRate]:
        where, params = self._filters(exchange_id, symbol)
        rows = await self.db.fetch_all(
            f"""
            SELECT * FROM funding_rates
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [
            FundingRate(
                exchange_id=row["exchange_id"],
                symbol=row["symbol"],
                timestamp=from_iso(row["timestamp"]),
                rate=float(row["rate"]),
                next_funding_time=from_iso(row["next_funding_time"]),
            )
            for row in rows
        ]

    async def latest_funding_rate(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
    ) -> FundingRate | None:
        history = await self.funding_history(exchange_id, symbol, limit=1)
        return history[0] if history else None

    async def average_funding_rates(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
        now: datetime | None = None,
    ) -> list[AverageFundingRate]:
        current_time = now or await self._latest_funding_timestamp(exchange_id, symbol)
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        results: list[AverageFundingRate] = []
        base_where, base_params = self._filters(exchange_id, symbol)
        for label, seconds in DEFAULT_AVERAGE_WINDOWS.items():
            since = current_time - timedelta(seconds=seconds)
            if base_where:
                where = f"{base_where} AND timestamp >= ?"
                params = (*base_params, to_iso(since))
            else:
                where = "WHERE timestamp >= ?"
                params = (to_iso(since),)
            row = await self.db.fetch_one(
                f"""
                SELECT
                    AVG(rate) AS avg_rate,
                    MIN(rate) AS min_rate,
                    MAX(rate) AS max_rate,
                    COUNT(*) AS samples
                FROM funding_rates
                {where}
                """,
                params,
            )
            samples = int(row["samples"] or 0) if row is not None else 0
            results.append(
                AverageFundingRate(
                    window=label,
                    avg_rate=None if samples == 0 else float(row["avg_rate"]),
                    min_rate=None if samples == 0 else float(row["min_rate"]),
                    max_rate=None if samples == 0 else float(row["max_rate"]),
                    samples=samples,
                )
            )
        return results

    async def _latest_funding_timestamp(
        self,
        exchange_id: str | None,
        symbol: str | None,
    ) -> datetime | None:
        where, params = self._filters(exchange_id, symbol)
        row = await self.db.fetch_one(
            f"""
            SELECT timestamp FROM funding_rates
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return None if row is None else from_iso(row["timestamp"])

    async def prune_market_data(
        self,
        retention_days: int = MARKET_RETENTION_DAYS,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time - timedelta(days=retention_days)
        row = await self.db.fetch_one(
            "SELECT COUNT(*) AS count FROM market_snapshots WHERE timestamp < ?",
            (to_iso(cutoff),),
        )
        deleted = int(row["count"] if row else 0)
        await self.db.execute(
            "DELETE FROM market_snapshots WHERE timestamp < ?",
            (to_iso(cutoff),),
        )
        return deleted

    async def snapshot_count(self) -> int:
        row = await self.db.fetch_one("SELECT COUNT(*) AS count FROM market_snapshots")
        return int(row["count"] if row else 0)

    async def funding_count(self) -> int:
        row = await self.db.fetch_one("SELECT COUNT(*) AS count FROM funding_rates")
        return int(row["count"] if row else 0)

    async def orderbook_level_count(self) -> int:
        row = await self.db.fetch_one("SELECT COUNT(*) AS count FROM orderbook_levels")
        return int(row["count"] if row else 0)

    async def mark_collection_success(
        self,
        exchange_id: str,
        symbol: str,
        collected_at: datetime,
        next_collection_at: datetime | None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO collector_market_status (
                exchange_id, symbol, last_success_at, last_failure_at,
                consecutive_failures, last_error, next_collection_at, updated_at
            )
            VALUES (?, ?, ?, NULL, 0, NULL, ?, ?)
            ON CONFLICT(exchange_id, symbol) DO UPDATE SET
                last_success_at = excluded.last_success_at,
                consecutive_failures = 0,
                last_error = NULL,
                next_collection_at = excluded.next_collection_at,
                updated_at = excluded.updated_at
            """,
            (
                exchange_id,
                symbol,
                to_iso(collected_at),
                None if next_collection_at is None else to_iso(next_collection_at),
                to_iso(collected_at),
            ),
        )

    async def mark_collection_failure(
        self,
        exchange_id: str,
        symbol: str,
        failed_at: datetime,
        error_message: str,
        next_collection_at: datetime | None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO collector_market_status (
                exchange_id, symbol, last_success_at, last_failure_at,
                consecutive_failures, last_error, next_collection_at, updated_at
            )
            VALUES (?, ?, NULL, ?, 1, ?, ?, ?)
            ON CONFLICT(exchange_id, symbol) DO UPDATE SET
                last_failure_at = excluded.last_failure_at,
                consecutive_failures = collector_market_status.consecutive_failures + 1,
                last_error = excluded.last_error,
                next_collection_at = excluded.next_collection_at,
                updated_at = excluded.updated_at
            """,
            (
                exchange_id,
                symbol,
                to_iso(failed_at),
                error_message[:500],
                None if next_collection_at is None else to_iso(next_collection_at),
                to_iso(failed_at),
            ),
        )

    async def collector_statuses(
        self,
        exchange_id: str | None = None,
        symbol: str | None = None,
    ) -> list[CollectorMarketStatus]:
        where, params = self._filters(exchange_id, symbol)
        rows = await self.db.fetch_all(
            f"""
            SELECT * FROM collector_market_status
            {where}
            ORDER BY exchange_id ASC, symbol ASC
            """,
            params,
        )
        return [
            CollectorMarketStatus(
                exchange_id=row["exchange_id"],
                symbol=row["symbol"],
                last_success_at=None
                if row["last_success_at"] is None
                else from_iso(row["last_success_at"]),
                last_failure_at=None
                if row["last_failure_at"] is None
                else from_iso(row["last_failure_at"]),
                consecutive_failures=int(row["consecutive_failures"]),
                last_error=row["last_error"],
                next_collection_at=None
                if row["next_collection_at"] is None
                else from_iso(row["next_collection_at"]),
                updated_at=from_iso(row["updated_at"]),
            )
            for row in rows
        ]

    async def _hydrate_snapshot(self, snapshot_id: int) -> MarketSnapshot:
        row = await self.db.fetch_one(
            "SELECT * FROM market_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        if row is None:
            raise LookupError(f"Snapshot {snapshot_id} not found")
        levels = await self.db.fetch_all(
            """
            SELECT * FROM orderbook_levels
            WHERE snapshot_id = ?
            ORDER BY side ASC, level_index ASC
            """,
            (snapshot_id,),
        )
        bids = tuple(
            OrderBookLevel(
                side=BookSide.BID,
                price=float(level["price"]),
                size=float(level["size"]),
                level_index=int(level["level_index"]),
            )
            for level in levels
            if level["side"] == BookSide.BID.value
        )
        asks = tuple(
            OrderBookLevel(
                side=BookSide.ASK,
                price=float(level["price"]),
                size=float(level["size"]),
                level_index=int(level["level_index"]),
            )
            for level in levels
            if level["side"] == BookSide.ASK.value
        )
        return MarketSnapshot(
            exchange_id=row["exchange_id"],
            symbol=row["symbol"],
            timestamp=from_iso(row["timestamp"]),
            mark_price=float(row["mark_price"]),
            index_price=float(row["index_price"]),
            best_bid=float(row["best_bid"]),
            best_ask=float(row["best_ask"]),
            bids=bids,
            asks=asks,
        )

    def _filters(
        self,
        exchange_id: str | None,
        symbol: str | None,
    ) -> tuple[str, tuple[str, ...]]:
        clauses: list[str] = []
        params: list[str] = []
        if exchange_id:
            clauses.append("exchange_id = ?")
            params.append(exchange_id)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if not clauses:
            return "", tuple(params)
        return "WHERE " + " AND ".join(clauses), tuple(params)
