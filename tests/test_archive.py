from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing
from datetime import date, datetime, timezone

from perpdex_bot.archive import archive_month, default_archive_year_month
from perpdex_bot.db import SCHEMA
from perpdex_bot.models import to_iso


def test_default_archive_month_is_two_months_before_now() -> None:
    assert default_archive_year_month(date(2026, 7, 1)) == (2026, 5)
    assert default_archive_year_month(date(2026, 1, 1)) == (2025, 11)


def test_archive_month_moves_month_to_compressed_sqlite(tmp_path) -> None:
    db_path = tmp_path / "live.sqlite"
    archive_dir = tmp_path / "archives"
    _create_sample_db(db_path)

    result = archive_month(db_path, archive_dir=archive_dir, now=date(2026, 7, 1))

    assert result.created is True
    assert result.year_month == "2026-05"
    assert result.snapshot_rows == 1
    assert result.orderbook_rows == 2
    assert result.funding_rows == 1
    assert result.archive_zip_path is not None
    assert result.archive_zip_path.exists()

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT symbol FROM market_snapshots").fetchone()[0] == "ETH-PERP"
        assert conn.execute("SELECT COUNT(*) FROM orderbook_levels").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM funding_rates").fetchone()[0] == 1

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    with zipfile.ZipFile(result.archive_zip_path) as archive_zip:
        archive_zip.extractall(extracted_dir)

    archived_db = extracted_dir / "perpdex_2026-05.sqlite"
    with closing(sqlite3.connect(archived_db)) as conn:
        assert conn.execute("SELECT symbol FROM market_snapshots").fetchone()[0] == "BTC-PERP"
        assert conn.execute("SELECT COUNT(*) FROM orderbook_levels").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM funding_rates").fetchone()[0] == 1


def _create_sample_db(path) -> None:
    may = datetime(2026, 5, 15, 12, tzinfo=timezone.utc)
    june = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT INTO market_snapshots (
                id, exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "Hibachi", "BTC-PERP", to_iso(may), 100.0, 100.0, 99.0, 101.0, 2.0, 200.0),
        )
        conn.execute(
            """
            INSERT INTO market_snapshots (
                id, exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (2, "Hibachi", "ETH-PERP", to_iso(june), 200.0, 200.0, 199.0, 201.0, 2.0, 100.0),
        )
        conn.executemany(
            """
            INSERT INTO orderbook_levels (snapshot_id, side, price, size, notional, level_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "bid", 99.0, 1.0, 99.0, 0),
                (1, "ask", 101.0, 1.0, 101.0, 0),
                (2, "bid", 199.0, 1.0, 199.0, 0),
                (2, "ask", 201.0, 1.0, 201.0, 0),
            ],
        )
        conn.executemany(
            """
            INSERT INTO funding_rates (exchange_id, symbol, timestamp, rate, next_funding_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("Hibachi", "BTC-PERP", to_iso(may), 0.0001, to_iso(may)),
                ("Hibachi", "ETH-PERP", to_iso(june), 0.0002, to_iso(june)),
            ],
        )
