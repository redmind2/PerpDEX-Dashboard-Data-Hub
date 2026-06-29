from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .calculations import estimate_slippage_grid
from .config import (
    DEFAULT_COLLECTOR_LOG_PATH,
    DEFAULT_AVERAGE_WINDOWS,
    DEFAULT_MARKET_CONFIG_PATH,
    DEFAULT_SLIPPAGE_NOTIONALS,
    collector_log_path,
    load_market_config,
)
from .models import BookSide, OrderBookLevel, SlippageEstimate, from_iso


TELEGRAM_TOKEN_ENV_VAR = "PERPDEX_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV_VAR = "PERPDEX_TELEGRAM_CHAT_ID"
TELEGRAM_STATUS_INTERVAL_ENV_VAR = "PERPDEX_TELEGRAM_STATUS_INTERVAL"
TELEGRAM_CHECK_INTERVAL_ENV_VAR = "PERPDEX_TELEGRAM_CHECK_INTERVAL"
TELEGRAM_STALE_AFTER_ENV_VAR = "PERPDEX_TELEGRAM_STALE_AFTER"
TELEGRAM_RUNNER_LOG_ENV_VAR = "PERPDEX_LIVE_RUNNER_LOG_PATH"
TELEGRAM_PID_PATH_ENV_VAR = "PERPDEX_LIVE_PID_PATH"

DEFAULT_STATUS_INTERVAL_SECONDS = 6 * 60 * 60
DEFAULT_CHECK_INTERVAL_SECONDS = 60
DEFAULT_STALE_AFTER_SECONDS = 15 * 60
DEFAULT_RUNNER_LOG_PATH = Path("data/logs/live-test-runner.log")
DEFAULT_PID_PATH = Path("data/live-test.pid")
LOG_ALERT_PATTERNS = (
    " error ",
    "error=",
    " exception ",
    "traceback",
    "collection failed",
    "failed to collect",
)


@dataclass(frozen=True)
class TelegramMonitorConfig:
    db_path: Path
    bot_token: str
    chat_id: str
    market_config_path: Path = DEFAULT_MARKET_CONFIG_PATH
    status_interval_seconds: int = DEFAULT_STATUS_INTERVAL_SECONDS
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS
    pid_path: Path = DEFAULT_PID_PATH
    runner_log_path: Path = DEFAULT_RUNNER_LOG_PATH
    collector_log_path: Path = DEFAULT_COLLECTOR_LOG_PATH
    dry_run: bool = False


@dataclass(frozen=True)
class DBStatus:
    db_path: Path
    db_size_bytes: int
    snapshot_count: int
    orderbook_level_count: int
    funding_count: int
    latest_snapshot_exchange: str | None
    latest_snapshot_symbol: str | None
    latest_snapshot_at: datetime | None
    active_failures: tuple[str, ...]


class LogCursor:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = path.stat().st_size if path.exists() else 0

    def read_new_lines(self) -> list[str]:
        if not self.path.exists():
            self.offset = 0
            return []
        size = self.path.stat().st_size
        if size < self.offset:
            self.offset = 0
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.offset)
            lines = handle.readlines()
            self.offset = handle.tell()
        return [line.rstrip() for line in lines]


def config_from_args(args: argparse.Namespace) -> TelegramMonitorConfig:
    bot_token = os.environ.get(TELEGRAM_TOKEN_ENV_VAR, "").strip()
    chat_id = os.environ.get(TELEGRAM_CHAT_ID_ENV_VAR, "").strip()
    if args.bot_token:
        bot_token = args.bot_token
    if args.chat_id:
        chat_id = args.chat_id
    return TelegramMonitorConfig(
        db_path=args.db,
        bot_token=bot_token,
        chat_id=chat_id,
        market_config_path=args.market_config,
        status_interval_seconds=args.status_interval,
        check_interval_seconds=args.check_interval,
        stale_after_seconds=args.stale_after,
        pid_path=args.pid_path,
        runner_log_path=args.runner_log,
        collector_log_path=args.collector_log,
        dry_run=args.dry_run,
    )


async def run_telegram_monitor(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    if not config.bot_token and not config.dry_run:
        raise SystemExit(f"Missing ${TELEGRAM_TOKEN_ENV_VAR} in .env or --bot-token")
    if not config.chat_id and not config.dry_run:
        raise SystemExit(f"Missing ${TELEGRAM_CHAT_ID_ENV_VAR} in .env or --chat-id")

    monitor = TelegramMonitor(config)
    if args.once:
        monitor.check_once(send_status=True)
        return
    monitor.run_forever()


class TelegramMonitor:
    def __init__(self, config: TelegramMonitorConfig) -> None:
        self.config = config
        self.runner_log = LogCursor(config.runner_log_path)
        self.collector_log = LogCursor(config.collector_log_path)
        self.last_issue_signature = ""
        self.telegram_update_offset: int | None = None

    def run_forever(self) -> None:
        next_status_at = 0.0
        while True:
            now = time.monotonic()
            send_status = now >= next_status_at
            self.check_once(send_status=send_status)
            if send_status:
                next_status_at = now + self.config.status_interval_seconds
            time.sleep(self.config.check_interval_seconds)

    def check_once(self, send_status: bool = False) -> None:
        issues: list[str] = []
        db_status = read_db_status(self.config.db_path)
        process_state = collector_process_state(self.config.pid_path)
        self.handle_commands(db_status, process_state)

        issues.extend(db_issues(db_status, self.config.stale_after_seconds))
        if process_state != "running":
            issues.append(f"collector process is {process_state}")
        issues.extend(log_issues(self.runner_log.read_new_lines(), "runner log"))
        issues.extend(log_issues(self.collector_log.read_new_lines(), "collector log"))

        if issues:
            signature = "\n".join(issues)
            if signature != self.last_issue_signature:
                self._send(format_issue_message(issues, db_status, process_state))
                self.last_issue_signature = signature
            return

        if self.last_issue_signature:
            self._send(format_recovery_message(db_status, process_state))
            self.last_issue_signature = ""
            return

        if send_status:
            self._send(format_status_message(db_status, process_state))

    def handle_commands(self, db_status: DBStatus, process_state: str) -> None:
        if self.config.dry_run:
            return
        updates = fetch_telegram_updates(self.config.bot_token, self.telegram_update_offset)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self.telegram_update_offset = update_id + 1
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if str(chat.get("id", "")) != str(self.config.chat_id):
                continue
            text = str(message.get("text", "")).strip()
            command = normalize_command(text)
            if command:
                self._send(
                    command_response(
                        command,
                        command_arguments(text),
                        self.config,
                        db_status,
                        process_state,
                    )
                )

    def _send(self, message: str) -> None:
        if self.config.dry_run:
            print(message)
            return
        send_telegram_message(self.config.bot_token, self.config.chat_id, message)


def read_db_status(path: Path) -> DBStatus:
    if not path.exists():
        return DBStatus(path, 0, 0, 0, 0, None, None, None, ("DB file does not exist",))

    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            snapshots = _count(conn, "market_snapshots")
            levels = _count(conn, "orderbook_levels")
            funding = _count(conn, "funding_rates")
            latest = conn.execute(
                """
                SELECT exchange_id, symbol, timestamp
                FROM market_snapshots
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            failures = conn.execute(
                """
                SELECT exchange_id, symbol, consecutive_failures, last_error
                FROM collector_market_status
                WHERE consecutive_failures > 0
                ORDER BY exchange_id ASC, symbol ASC
                """
            ).fetchall()
    except sqlite3.Error as exc:
        return DBStatus(path, path.stat().st_size, 0, 0, 0, None, None, None, (f"DB read failed: {exc}",))

    return DBStatus(
        db_path=path,
        db_size_bytes=path.stat().st_size,
        snapshot_count=snapshots,
        orderbook_level_count=levels,
        funding_count=funding,
        latest_snapshot_exchange=None if latest is None else str(latest["exchange_id"]),
        latest_snapshot_symbol=None if latest is None else str(latest["symbol"]),
        latest_snapshot_at=None if latest is None else from_iso(str(latest["timestamp"])),
        active_failures=tuple(
            (
                f"{row['exchange_id']} {row['symbol']} "
                f"failures={row['consecutive_failures']} error={row['last_error']}"
            )
            for row in failures
        ),
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if row else 0)


def db_issues(status: DBStatus, stale_after_seconds: int) -> list[str]:
    issues = list(status.active_failures)
    if not status.db_path.exists():
        return issues
    if status.latest_snapshot_at is None:
        issues.append("DB has no market snapshots")
        return issues
    age = (datetime.now(timezone.utc) - status.latest_snapshot_at).total_seconds()
    if age > stale_after_seconds:
        issues.append(
            f"latest snapshot is stale: {format_age(int(age))} old "
            f"(threshold {format_age(stale_after_seconds)})"
        )
    return issues


def collector_process_state(pid_path: Path) -> str:
    if not pid_path.exists():
        return f"unknown; PID file missing at {pid_path}"
    raw_pid = pid_path.read_text(encoding="utf-8-sig").strip()
    try:
        pid = int(raw_pid)
    except ValueError:
        return f"unknown; invalid PID value {raw_pid!r}"
    return "running" if process_is_running(pid) else f"stopped; PID {pid} is not running"


def process_is_running(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def log_issues(lines: list[str], source: str) -> list[str]:
    matches: list[str] = []
    for line in lines:
        lowered = f" {line.lower()} "
        if any(pattern in lowered for pattern in LOG_ALERT_PATTERNS):
            matches.append(f"{source}: {line[:300]}")
    return matches


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def fetch_telegram_updates(bot_token: str, offset: int | None) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "timeout": 0,
        "limit": 20,
        "allowed_updates": json.dumps(["message", "channel_post"]),
    }
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    if not payload.get("ok"):
        return []
    result = payload.get("result", [])
    return result if isinstance(result, list) else []


def normalize_command(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    first_token = text.split()[0].lower()
    return first_token.split("@", 1)[0]


def command_response(
    command: str,
    args: list[str],
    config: TelegramMonitorConfig,
    status: DBStatus,
    process_state: str,
) -> str:
    if command in {"/help", "/start"}:
        return format_help_message()
    if command == "/status":
        return format_status_message(status, process_state)
    if command == "/storage":
        return format_storage_message(status)
    if command == "/markets":
        return format_markets_message(config.market_config_path)
    if command == "/failures":
        return format_failures_message(status)
    if command == "/slippage":
        return format_slippage_command(config.db_path, args)
    if command == "/spreads":
        return format_spreads_command(config.db_path, args)
    return "Unknown command. Send /help to see available commands."


def format_help_message() -> str:
    return "\n".join(
        (
            "PerpDEX monitor commands",
            "/help - show this command list",
            "/status - show collector and DB health",
            "/storage - show DB size and row counts",
            "/markets - show monitored exchanges and markets",
            "/failures - show active collector failures",
            "/slippage EXCHANGE SYMBOL - show simple slippage, for example /slippage Hibachi BTC-PERP",
            "/spreads - show spread rows for every monitored market",
            "/spreads EXCHANGE - show spread rows for one exchange",
            "/spreads SYMBOL - show spread rows for one market across exchanges",
            "/spreads EXCHANGE SYMBOL - show one market, for example /spreads Hibachi BTC-PERP",
            "",
            "Automatic monitor: OK report every 6 hours, instant alert on collector/DB/log issues.",
        )
    )


def format_status_message(status: DBStatus, process_state: str) -> str:
    return "\n".join(
        (
            "[OK] PerpDEX running",
            f"collector: {process_state}",
            f"DB: {status.db_path}",
            f"DB size: {format_bytes(status.db_size_bytes)}",
            f"market snapshots: {status.snapshot_count:,}",
            f"orderbook levels: {status.orderbook_level_count:,}",
            f"funding rates: {status.funding_count:,}",
            f"latest snapshot: {format_latest_snapshot(status)}",
        )
    )


def format_issue_message(issues: list[str], status: DBStatus, process_state: str) -> str:
    lines = [
        "[ALERT] PerpDEX issue detected",
        f"collector: {process_state}",
        f"DB size: {format_bytes(status.db_size_bytes)}",
        f"latest snapshot: {format_latest_snapshot(status)}",
        "issues:",
    ]
    lines.extend(f"- {issue}" for issue in issues)
    return "\n".join(lines)


def format_recovery_message(status: DBStatus, process_state: str) -> str:
    return "\n".join(
        (
            "[OK] PerpDEX issue resolved",
            f"collector: {process_state}",
            f"DB size: {format_bytes(status.db_size_bytes)}",
            f"latest snapshot: {format_latest_snapshot(status)}",
        )
    )


def format_storage_message(status: DBStatus) -> str:
    return "\n".join(
        (
            "PerpDEX DB storage",
            f"DB: {status.db_path}",
            f"DB size: {format_bytes(status.db_size_bytes)}",
            f"market snapshots: {status.snapshot_count:,}",
            f"orderbook levels: {status.orderbook_level_count:,}",
            f"funding rates: {status.funding_count:,}",
        )
    )


def format_markets_message(path: Path) -> str:
    markets = load_market_config(path)
    lines = ["PerpDEX monitored markets"]
    total = 0
    for market in markets:
        total += len(market.symbols)
        lines.append(f"- {market.exchange_id}: {', '.join(market.symbols)}")
    lines.append(f"Total: {len(markets)} exchanges, {total} markets")
    return "\n".join(lines)


def format_failures_message(status: DBStatus) -> str:
    if not status.active_failures:
        return "No active collector failures."
    lines = ["Active collector failures"]
    lines.extend(f"- {failure}" for failure in status.active_failures)
    return "\n".join(lines)


def command_arguments(text: str) -> list[str]:
    parts = text.split()
    return parts[1:] if len(parts) > 1 else []


def format_slippage_command(db_path: Path, args: list[str]) -> str:
    if len(args) < 2:
        return "Usage: /slippage EXCHANGE SYMBOL\nExample: /slippage Hibachi BTC-PERP"
    exchange_id = args[0]
    symbol = args[1].upper()
    book = read_latest_orderbook(db_path, exchange_id, symbol)
    if book is None:
        return f"No market data found for {exchange_id} {symbol}."
    snapshot, bids, asks = book
    estimates = estimate_slippage_grid(
        DEFAULT_SLIPPAGE_NOTIONALS,
        reference_price=snapshot["mid_price"],
        bids=bids,
        asks=asks,
    )
    return format_simple_slippage_message(snapshot, estimates)


def format_spreads_command(db_path: Path, args: list[str]) -> str:
    if len(args) == 0:
        return format_spread_rows_message(read_spread_rows(db_path), "all exchanges all markets")
    elif len(args) == 1 and _looks_like_symbol(args[0]):
        symbol = args[0].upper()
        return format_spread_rows_message(read_spread_rows(db_path, symbol=symbol), f"all exchanges {symbol}")
    elif len(args) == 1:
        exchange_id = args[0]
        return format_spread_rows_message(read_spread_rows(db_path, exchange_id=exchange_id), f"{exchange_id} all markets")
    else:
        summary = read_spread_summary(db_path, exchange_id=args[0], symbol=args[1].upper())
        if summary is None:
            return f"No spread data found for {' '.join(args)}."
        return format_spread_summary_message(summary)


def read_spread_rows(
    db_path: Path,
    exchange_id: str | None = None,
    symbol: str | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    rows: list[dict[str, object]] = []
    windows = ("5m", "1h", "24h")
    with sqlite3.connect(uri, uri=True, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        latest_rows = conn.execute(
            """
            SELECT latest.*
            FROM market_snapshots latest
            JOIN (
                SELECT exchange_id, symbol, MAX(id) AS latest_id
                FROM market_snapshots
                WHERE (? IS NULL OR lower(exchange_id) = lower(?))
                  AND (? IS NULL OR upper(symbol) = upper(?))
                GROUP BY exchange_id, symbol
            ) grouped ON grouped.latest_id = latest.id
            ORDER BY latest.exchange_id ASC, latest.symbol ASC
            """,
            (exchange_id, exchange_id, symbol, symbol),
        ).fetchall()
        for latest in latest_rows:
            latest_at = from_iso(str(latest["timestamp"]))
            averages: dict[str, tuple[float | None, int]] = {}
            for label in windows:
                seconds = DEFAULT_AVERAGE_WINDOWS[label]
                since = datetime.fromtimestamp(latest_at.timestamp() - seconds, timezone.utc).isoformat()
                avg = conn.execute(
                    """
                    SELECT AVG(spread_bps) AS avg_spread_bps,
                           COUNT(*) AS samples
                    FROM market_snapshots
                    WHERE exchange_id = ?
                      AND symbol = ?
                      AND timestamp >= ?
                    """,
                    (latest["exchange_id"], latest["symbol"], since),
                ).fetchone()
                samples = int(avg["samples"] or 0) if avg else 0
                averages[label] = (
                    None if samples < 2 else float(avg["avg_spread_bps"]),
                    samples,
                )
            rows.append(
                {
                    "exchange_id": str(latest["exchange_id"]),
                    "symbol": str(latest["symbol"]),
                    "timestamp": latest_at,
                    "spread_bps": float(latest["spread_bps"]),
                    "averages": averages,
                }
            )
    return rows


def format_spread_rows_message(rows: list[dict[str, object]], scope: str) -> str:
    if not rows:
        return f"No spread data found for {scope}."
    lines = [
        f"Spreads {scope}",
        "market current 5m 1h 24h",
    ]
    for row in rows:
        averages = row["averages"]
        lines.append(
            f"{row['exchange_id']} {row['symbol']} "
            f"{format_bps(row['spread_bps'])} "
            f"{_avg_bps(averages['5m'])} "
            f"{_avg_bps(averages['1h'])} "
            f"{_avg_bps(averages['24h'])}"
        )
    return "\n".join(lines)


def _avg_bps(value: tuple[float | None, int]) -> str:
    avg, samples = value
    if avg is None:
        return f"n/a({samples})"
    return f"{avg:.2f}({samples})"


def read_spread_summary(
    db_path: Path,
    exchange_id: str | None = None,
    symbol: str | None = None,
) -> dict[str, object] | None:
    if not db_path.exists():
        return None
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        latest = conn.execute(
            """
            SELECT exchange_id, symbol, timestamp, best_bid, best_ask, spread, spread_bps
            FROM market_snapshots
            WHERE (? IS NULL OR lower(exchange_id) = lower(?))
              AND (? IS NULL OR upper(symbol) = upper(?))
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (exchange_id, exchange_id, symbol, symbol),
        ).fetchone()
        if latest is None:
            return None
        latest_at = from_iso(str(latest["timestamp"]))
        averages = []
        for label, seconds in DEFAULT_AVERAGE_WINDOWS.items():
            since = latest_at.timestamp() - seconds
            row = conn.execute(
                """
                SELECT AVG(spread) AS avg_spread,
                       AVG(spread_bps) AS avg_spread_bps,
                       COUNT(*) AS samples
                FROM market_snapshots
                WHERE (? IS NULL OR lower(exchange_id) = lower(?))
                  AND (? IS NULL OR upper(symbol) = upper(?))
                  AND timestamp >= ?
                """,
                (
                    exchange_id,
                    exchange_id,
                    symbol,
                    symbol,
                    datetime.fromtimestamp(since, timezone.utc).isoformat(),
                ),
            ).fetchone()
            samples = int(row["samples"] or 0) if row else 0
            averages.append(
                {
                    "window": label,
                    "avg_spread": None if samples < 2 else float(row["avg_spread"]),
                    "avg_spread_bps": None if samples < 2 else float(row["avg_spread_bps"]),
                    "samples": samples,
                }
            )
        current = conn.execute(
            """
            SELECT AVG(spread) AS avg_spread,
                   AVG(spread_bps) AS avg_spread_bps,
                   COUNT(*) AS markets
            FROM market_snapshots
            WHERE id IN (
                SELECT MAX(id)
                FROM market_snapshots
                WHERE (? IS NULL OR lower(exchange_id) = lower(?))
                  AND (? IS NULL OR upper(symbol) = upper(?))
                GROUP BY exchange_id, symbol
            )
            """,
            (exchange_id, exchange_id, symbol, symbol),
        ).fetchone()
        current_markets = int(current["markets"] or 0) if current else 0
    return {
        "scope": _spread_scope_label(exchange_id, symbol),
        "latest_market": f"{latest['exchange_id']} {latest['symbol']}",
        "timestamp": latest_at,
        "best_bid": float(latest["best_bid"]),
        "best_ask": float(latest["best_ask"]),
        "spread": float(latest["spread"]),
        "spread_bps": float(latest["spread_bps"]),
        "current_avg_spread": None if current_markets == 0 else float(current["avg_spread"]),
        "current_avg_spread_bps": None if current_markets == 0 else float(current["avg_spread_bps"]),
        "current_markets": current_markets,
        "averages": averages,
    }


def format_spread_summary_message(summary: dict[str, object]) -> str:
    lines = [
        f"Spreads {summary['scope']}",
        f"latest sample: {summary['latest_market']} {summary['timestamp']}",
        (
            f"latest market: spread={format_money(float(summary['spread']))} "
            f"{format_bps(float(summary['spread_bps']))} "
            f"bid={format_money(float(summary['best_bid']))} "
            f"ask={format_money(float(summary['best_ask']))}"
        ),
        (
            f"current avg: spread={format_money(summary['current_avg_spread'])} "
            f"{format_bps(summary['current_avg_spread_bps'])} "
            f"markets={summary['current_markets']}"
        ),
        "averages:",
    ]
    for item in summary["averages"]:
        avg_spread = item["avg_spread"]
        avg_spread_bps = item["avg_spread_bps"]
        lines.append(
            f"{item['window']}: spread={format_money(avg_spread)} "
            f"{format_bps(avg_spread_bps)} samples={item['samples']}"
        )
    return "\n".join(lines)


def _looks_like_symbol(value: str) -> bool:
    normalized = value.upper()
    return normalized.endswith("-PERP") or normalized.endswith("USD")


def _spread_scope_label(exchange_id: str | None, symbol: str | None) -> str:
    if exchange_id and symbol:
        return f"{exchange_id} {symbol}"
    if exchange_id:
        return f"{exchange_id} all markets"
    if symbol:
        return f"all exchanges {symbol}"
    return "all exchanges all markets"


def read_latest_orderbook(
    db_path: Path,
    exchange_id: str,
    symbol: str,
) -> tuple[dict[str, object], tuple[OrderBookLevel, ...], tuple[OrderBookLevel, ...]] | None:
    if not db_path.exists():
        return None
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        snapshot = conn.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE lower(exchange_id) = lower(?) AND upper(symbol) = upper(?)
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (exchange_id, symbol),
        ).fetchone()
        if snapshot is None:
            return None
        levels = conn.execute(
            """
            SELECT side, price, size, level_index
            FROM orderbook_levels
            WHERE snapshot_id = ?
            ORDER BY side ASC, level_index ASC
            """,
            (snapshot["id"],),
        ).fetchall()
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
    mid_price = (float(snapshot["best_bid"]) + float(snapshot["best_ask"])) / 2
    return (
        {
            "exchange_id": str(snapshot["exchange_id"]),
            "symbol": str(snapshot["symbol"]),
            "timestamp": from_iso(str(snapshot["timestamp"])),
            "mid_price": mid_price,
        },
        bids,
        asks,
    )


def format_simple_slippage_message(
    snapshot: dict[str, object],
    estimates: list[SlippageEstimate],
) -> str:
    lines = [
        f"Slippage {snapshot['exchange_id']} {snapshot['symbol']}",
        f"latest: {snapshot['timestamp']}",
        "side notional slippage filled",
    ]
    for item in estimates:
        complete = "" if item.complete else " partial"
        lines.append(
            f"{item.side.value} {format_notional(item.notional_usd)} "
            f"{format_bps(item.slippage_bps)} filled={format_notional(item.filled_notional)}{complete}"
        )
    return "\n".join(lines)


def format_notional(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def format_bps(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}bps"


def format_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) <= 10:
        return f"${value:,.4f}"
    return f"${value:,.2f}"


def format_latest_snapshot(status: DBStatus) -> str:
    if status.latest_snapshot_at is None:
        return "n/a"
    age_seconds = int((datetime.now(timezone.utc) - status.latest_snapshot_at).total_seconds())
    return (
        f"{status.latest_snapshot_exchange} {status.latest_snapshot_symbol} "
        f"{status.latest_snapshot_at.isoformat()} ({format_age(age_seconds)} old)"
    )


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
