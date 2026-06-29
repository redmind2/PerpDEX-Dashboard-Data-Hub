from __future__ import annotations

import asyncio

from perpdex_bot.lighter import LighterPublicCollector, to_lighter_market


class FakeLighterClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, int | str]] = []

        class Settings:
            orderbook_depth_limit = 3

        self.settings = Settings()

    async def market_detail(self, api_symbol: str):
        self.requests.append(("market_detail", api_symbol))
        assert api_symbol == "SKHYNIXUSD"
        return {
            "symbol": "SKHYNIXUSD",
            "market_id": 161,
            "status": "active",
            "last_trade_price": 1704.324,
        }

    async def order_book_orders(self, market_id: int, limit: int):
        self.requests.append(("order_book_orders", market_id))
        assert market_id == 161
        assert limit == 3
        return {
            "bids": [
                {"price": "1704.2", "remaining_base_amount": "1.5"},
                {"price": "1704.1", "remaining_base_amount": "2.0"},
            ],
            "asks": [
                {"price": "1704.6", "remaining_base_amount": "1.25"},
                {"price": "1704.7", "remaining_base_amount": "3.0"},
            ],
        }

    async def funding_rate(self, market_id: int):
        self.requests.append(("funding_rate", market_id))
        assert market_id == 161
        return {
            "market_id": 161,
            "exchange": "lighter",
            "symbol": "SKHYNIXUSD",
            "rate": 0.0004,
        }


def test_lighter_symbol_mapping_keeps_requested_aliases() -> None:
    assert to_lighter_market("BTC-PERP").api_symbol == "BTC"
    assert to_lighter_market("HYPE-PERP").api_symbol == "HYPE"
    assert to_lighter_market("SAMSUNG-PERP").api_symbol == "SAMSUNGUSD"
    assert to_lighter_market("SKHYNICS-PERP").api_symbol == "SKHYNIXUSD"
    assert to_lighter_market("WTI-PERP").api_symbol == "WTI"
    assert to_lighter_market("BRENT-PERP").api_symbol == "BRENTOIL"
    assert to_lighter_market("XAU-PERP").api_symbol == "XAU"
    assert to_lighter_market("XAG-PERP").api_symbol == "XAG"


def test_lighter_collector_builds_phase1_models() -> None:
    client = FakeLighterClient()
    collector = LighterPublicCollector(client=client)  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("SKHYNICS-PERP"))

    assert result.snapshot.exchange_id == "Lighter"
    assert result.snapshot.symbol == "SKHYNICS-PERP"
    assert result.snapshot.best_bid == 1704.2
    assert result.snapshot.best_ask == 1704.6
    assert result.snapshot.mark_price == 1704.324
    assert result.snapshot.index_price == 1704.324
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.0004]
    assert client.requests == [
        ("market_detail", "SKHYNIXUSD"),
        ("order_book_orders", 161),
        ("funding_rate", 161),
    ]
