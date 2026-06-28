from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_PATH = Path("data/perpdex_phase1.sqlite")
DEFAULT_MARKET_CONFIG_PATH = Path("config/markets.json")
DEFAULT_COLLECTOR_LOG_PATH = Path("data/logs/collector.log")
MARKET_SNAPSHOT_INTERVAL_SECONDS = 60
MARKET_RETENTION_DAYS = 90
STALE_DATA_SECONDS = 3 * 60
DEFAULT_LIVE_MARKETS = ("BTC-PERP", "ETH-PERP", "EUR-PERP")
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
