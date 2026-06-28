from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from perpdex_bot.hibachi import (
    HibachiPublicCollector,
    _snapshot_from_payload,
    orderbook_granularity_for,
    to_hibachi_symbol,
)


class FakeHibachiClient:
    def __init__(self) -> None:
        self.settings = type(
            "Settings",
            (),
            {"orderbook_depth_limit": 100, "orderbook_granularity": 0.1},
        )()

    async def get_json(self, path: str, params: dict[str, object] | None = None):
        if path == "/market/data/orderbook":
            return {
                "bid": {
                    "levels": [
                        {"price": "99.50", "quantity": "3"},
                        {"price": "100.00", "quantity": "2"},
                    ]
                },
                "ask": {
                    "levels": [
                        {"price": "101.50", "quantity": "3"},
                        {"price": "101.00", "quantity": "2"},
                    ]
                },
            }
        if path == "/market/data/prices":
            return {
                "askPrice": "101.00",
                "bidPrice": "100.00",
                "fundingRateEstimation": {
                    "estimatedFundingRate": "0.0001",
                    "nextFundingTimestamp": 1_720_028_800,
                },
                "markPrice": "100.50",
                "spotPrice": "100.25",
                "symbol": params["symbol"],
                "tradePrice": "100.75",
            }
        raise AssertionError(f"Unexpected path: {path}")


def test_symbol_mapping() -> None:
    assert to_hibachi_symbol("BTC-PERP") == "BTC/USDT-P"
    assert to_hibachi_symbol("EUR-PERP") == "EUR/USDT-P"


def test_eur_uses_smaller_orderbook_granularity() -> None:
    assert orderbook_granularity_for("BTC-PERP", 0.1) == 0.1
    assert orderbook_granularity_for("EUR-PERP", 0.1) == 0.0001


def test_hibachi_collector_builds_phase1_models() -> None:
    collector = HibachiPublicCollector(client=FakeHibachiClient())  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("BTC-PERP"))

    assert result.snapshot.exchange_id == "Hibachi"
    assert result.snapshot.symbol == "BTC-PERP"
    assert result.snapshot.best_bid == 100.0
    assert result.snapshot.best_ask == 101.0
    assert result.snapshot.mark_price == 100.5
    assert result.snapshot.index_price == 100.25
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.0001]


def test_hibachi_null_orderbook_raises_clear_error() -> None:
    prices = {
        "fundingRateEstimation": {
            "estimatedFundingRate": "0.0001",
            "nextFundingTimestamp": 1_720_028_800,
        },
        "markPrice": "1.13",
        "spotPrice": "1.13",
    }

    try:
        _snapshot_from_payload(
            "Hibachi",
            "EUR-PERP",
            datetime.now(timezone.utc),
            {"ask": None, "bid": None},
            prices,
        )
    except ValueError as exc:
        assert "orderbook response did not include both bids and asks" in str(exc)
    else:
        raise AssertionError("Expected a clear ValueError for null orderbook sides")