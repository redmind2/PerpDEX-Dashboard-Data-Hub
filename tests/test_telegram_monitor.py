from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from perpdex_bot.db import SCHEMA
from perpdex_bot.telegram_monitor import (
    TelegramMonitorConfig,
    command_response,
    db_issues,
    format_bytes,
    format_order_spread_command,
    format_spreads_command,
    format_slippage_command,
    log_issues,
    normalize_command,
    read_db_status,
)


def test_format_bytes_uses_human_readable_units() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(2 * 1024 * 1024) == "2.0 MB"


def test_log_issues_detects_new_error_lines() -> None:
    lines = [
        "Collected public data: Hibachi BTC-PERP",
        "Collection failed: Hibachi ETH-PERP error=ValueError: bad book",
    ]

    assert log_issues(lines, "runner log") == [
        "runner log: Collection failed: Hibachi ETH-PERP error=ValueError: bad book"
    ]


def test_command_response_help_lists_interactive_commands(tmp_path) -> None:
    config = TelegramMonitorConfig(
        db_path=tmp_path / "monitor.sqlite",
        bot_token="token",
        chat_id="chat",
    )
    status = read_db_status(config.db_path)

    output = command_response("/help", [], config, status, "running")

    assert "/markets" in output
    assert "/slippage SYMBOL" in output
    assert "/orderspread SYMBOL" in output
    assert "/spreads EXCHANGE SYMBOL" in output
    assert normalize_command("/status@PerpDEXDashboardbot") == "/status"


def test_read_db_status_and_stale_issue(tmp_path) -> None:
    db_path = tmp_path / "monitor.sqlite"
    old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=30)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT INTO market_snapshots (
                exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Hibachi",
                "BTC-PERP",
                old_timestamp.isoformat(),
                100.0,
                100.0,
                99.0,
                101.0,
                2.0,
                200.0,
            ),
        )
        conn.commit()

    status = read_db_status(db_path)

    assert status.snapshot_count == 1
    assert status.latest_snapshot_exchange == "Hibachi"
    assert any("latest snapshot is stale" in issue for issue in db_issues(status, 60))


def test_format_slippage_command_reads_latest_orderbook(tmp_path) -> None:
    db_path = tmp_path / "monitor.sqlite"
    timestamp = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cursor = conn.execute(
            """
            INSERT INTO market_snapshots (
                exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Hibachi",
                "BTC-PERP",
                timestamp.isoformat(),
                100.0,
                100.0,
                99.0,
                101.0,
                2.0,
                200.0,
            ),
        )
        snapshot_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO orderbook_levels (
                snapshot_id, side, price, size, notional, level_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (snapshot_id, "bid", 99.0, 20000.0, 1_980_000.0, 0),
                (snapshot_id, "ask", 101.0, 20000.0, 2_020_000.0, 0),
            ],
        )
        conn.commit()

    output = format_slippage_command(db_path, ["Hibachi", "BTC-PERP"])
    market_output = format_slippage_command(db_path, ["BTC"])

    assert "Slippage Hibachi BTC-PERP" in output
    assert "buy $10k" in output
    assert "sell $1M" in output
    assert "Slippage all exchanges BTC-PERP" in market_output
    assert "Hibachi BTC-PERP" in market_output


def test_format_order_spread_command_uses_saved_orderbooks(tmp_path) -> None:
    db_path = tmp_path / "monitor.sqlite"
    timestamp = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cursor = conn.execute(
            """
            INSERT INTO market_snapshots (
                exchange_id, symbol, timestamp, mark_price, index_price,
                best_bid, best_ask, spread, spread_bps
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Hibachi",
                "BTC-PERP",
                timestamp.isoformat(),
                100.0,
                100.0,
                99.0,
                101.0,
                2.0,
                200.0,
            ),
        )
        snapshot_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO orderbook_levels (
                snapshot_id, side, price, size, notional, level_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (snapshot_id, "bid", 99.0, 20000.0, 1_980_000.0, 0),
                (snapshot_id, "ask", 101.0, 20000.0, 2_020_000.0, 0),
            ],
        )
        conn.commit()

    market_output = format_order_spread_command(db_path, ["BTC"])
    detail_output = format_order_spread_command(db_path, ["Hibachi", "BTC"])

    assert "OrderSpread all exchanges BTC-PERP" in market_output
    assert "Hibachi BTC-PERP" in market_output
    assert "OrderSpread Hibachi BTC-PERP" in detail_output
    assert "$100k" in detail_output


def test_format_spreads_command_supports_overall_exchange_and_market(tmp_path) -> None:
    db_path = tmp_path / "monitor.sqlite"
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        rows = [
            ("Hibachi", "BTC-PERP", now - timedelta(minutes=4), 100.0, 99.0, 101.0, 2.0, 200.0),
            ("Hibachi", "BTC-PERP", now, 100.0, 99.5, 100.5, 1.0, 100.0),
            ("Hibachi", "ETH-PERP", now, 200.0, 199.0, 201.0, 2.0, 100.0),
            ("Rise", "BTC-PERP", now, 101.0, 100.0, 102.0, 2.0, 198.02),
        ]
        for exchange, symbol, timestamp, mark, bid, ask, spread, spread_bps in rows:
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    exchange_id, symbol, timestamp, mark_price, index_price,
                    best_bid, best_ask, spread, spread_bps
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exchange,
                    symbol,
                    timestamp.isoformat(),
                    mark,
                    mark,
                    bid,
                    ask,
                    spread,
                    spread_bps,
                ),
            )
        conn.commit()

    overall = format_spreads_command(db_path, [])
    exchange = format_spreads_command(db_path, ["Hibachi"])
    market = format_spreads_command(db_path, ["BTC"])
    specific = format_spreads_command(db_path, ["Hibachi", "BTC"])

    assert "Spreads all exchanges all markets" in overall
    assert "Hibachi BTC-PERP" in overall
    assert "Rise BTC-PERP" in overall
    assert "Spreads Hibachi all markets" in exchange
    assert "Hibachi BTC-PERP" in exchange
    assert "Hibachi ETH-PERP" in exchange
    assert "Spreads all exchanges BTC-PERP" in market
    assert "Hibachi BTC-PERP" in market
    assert "Rise BTC-PERP" in market
    assert "Spreads Hibachi BTC-PERP" in specific
    assert "current:" in specific
