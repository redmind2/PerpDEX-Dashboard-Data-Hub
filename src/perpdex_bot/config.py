from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


DB_PATH_ENV_VAR = "PERPDEX_DB_PATH"
COLLECTION_INTERVAL_ENV_VAR = "PERPDEX_COLLECTION_INTERVAL"
ORDERBOOK_DEPTH_ENV_VAR = "PERPDEX_ORDERBOOK_DEPTH"
ORDERBOOK_MAX_NOTIONAL_DEPTH_ENV_VAR = "PERPDEX_MAX_NOTIONAL_DEPTH"
ORDERBOOK_GRANULARITY_ENV_VAR = "PERPDEX_ORDERBOOK_GRANULARITY"
PUBLIC_API_TIMEOUT_ENV_VAR = "PERPDEX_PUBLIC_API_TIMEOUT"
PUBLIC_API_RETRIES_ENV_VAR = "PERPDEX_PUBLIC_API_RETRIES"
COLLECTOR_LOG_PATH_ENV_VAR = "PERPDEX_COLLECTOR_LOG_PATH"
DEFAULT_DB_PATH = Path("data/perpdex_phase1.sqlite")
DEFAULT_MARKET_CONFIG_PATH = Path("config/markets.json")
DEFAULT_COLLECTOR_LOG_PATH = Path("data/logs/collector.log")
MARKET_SNAPSHOT_INTERVAL_SECONDS = 60
DEFAULT_ORDERBOOK_DEPTH_LIMIT = 100
DEFAULT_ORDERBOOK_GRANULARITY = 0.1
DEFAULT_PUBLIC_API_TIMEOUT_SECONDS = 10.0
DEFAULT_PUBLIC_API_RETRIES = 3
MARKET_RETENTION_DAYS = 90
STALE_DATA_SECONDS = 3 * 60
DEFAULT_LIVE_MARKETS = ("BTC-PERP", "ETH-PERP", "EUR-PERP", "SOL-PERP", "HYPE-PERP")
DEFAULT_SLIPPAGE_NOTIONALS = (10_000, 50_000, 100_000, 500_000, 1_000_000)
DEFAULT_AVERAGE_WINDOWS = {
    "1m": 60,
    "5m": 5 * 60,
    "1h": 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "14d": 14 * 24 * 60 * 60,
    "30d": 30 * 24 * 60 * 60,
}


@dataclass(frozen=True)
class RuntimeConfig:
    db_path: Path = DEFAULT_DB_PATH
    market_snapshot_interval_seconds: int = MARKET_SNAPSHOT_INTERVAL_SECONDS
    market_retention_days: int = MARKET_RETENTION_DAYS


@dataclass(frozen=True)
class MarketConfig:
    exchange_id: str
    symbols: tuple[str, ...]


def default_db_path() -> Path:
    raw_path = os.environ.get(DB_PATH_ENV_VAR, "").strip()
    return Path(raw_path) if raw_path else DEFAULT_DB_PATH


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value.strip())


def collection_interval_seconds() -> int:
    return _env_int(COLLECTION_INTERVAL_ENV_VAR, MARKET_SNAPSHOT_INTERVAL_SECONDS)


def orderbook_depth_limit() -> int:
    return _env_int(ORDERBOOK_DEPTH_ENV_VAR, DEFAULT_ORDERBOOK_DEPTH_LIMIT)


def orderbook_max_notional_depth() -> float | None:
    return _env_optional_float(ORDERBOOK_MAX_NOTIONAL_DEPTH_ENV_VAR)


def orderbook_granularity() -> float:
    return _env_float(ORDERBOOK_GRANULARITY_ENV_VAR, DEFAULT_ORDERBOOK_GRANULARITY)


def public_api_timeout_seconds() -> float:
    return _env_float(PUBLIC_API_TIMEOUT_ENV_VAR, DEFAULT_PUBLIC_API_TIMEOUT_SECONDS)


def public_api_retries() -> int:
    return _env_int(PUBLIC_API_RETRIES_ENV_VAR, DEFAULT_PUBLIC_API_RETRIES)


def collector_log_path() -> Path:
    raw_path = os.environ.get(COLLECTOR_LOG_PATH_ENV_VAR, "").strip()
    return Path(raw_path) if raw_path else DEFAULT_COLLECTOR_LOG_PATH


def load_market_config(path: Path = DEFAULT_MARKET_CONFIG_PATH) -> list[MarketConfig]:
    if not path.exists():
        return [MarketConfig(exchange_id="Hibachi", symbols=DEFAULT_LIVE_MARKETS)]

    raw = json.loads(path.read_text(encoding="utf-8"))
    markets = raw.get("markets", [])
    configs: list[MarketConfig] = []
    for market in markets:
        exchange_id = str(market.get("exchange", "Hibachi"))
        enabled = market.get("enabled", True)
        if not enabled:
            continue
        symbols = tuple(str(symbol).upper() for symbol in market.get("symbols", ()))
        if symbols:
            configs.append(MarketConfig(exchange_id=exchange_id, symbols=symbols))
    return configs or [MarketConfig(exchange_id="Hibachi", symbols=DEFAULT_LIVE_MARKETS)]


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return default if not raw else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return default if not raw else float(raw)


def _env_optional_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    return None if not raw else float(raw)
