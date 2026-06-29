from __future__ import annotations

import asyncio

from perpdex_bot.hotstuff import (
    HotstuffPublicCollector,
    find_hotstuff_ticker,
    to_hotstuff_symbol,
)


class FakeHotstuffClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def post_info(self, method: str, params: dict[str, object]):
        self.requests.append((method, params))
        if method == "ticker":
            return {
                "value": [
                    {
                        "type": "perp",
                        "symbol": "HYPE-PERP",
                        "mark_price": "62.72",
                        "mid_price": "62.739",
                        "index_price": "62.715991",
                        "best_bid_price": "62.737",
                        "best_ask_price": "62.741",
                        "best_bid_size": "20",
                        "best_ask_size": "20",
                        "funding_rate": "0.000024",
                        "last_updated": 1_782_716_289_738,
                    }
                ]
            }
        if method == "orderbook":
            return {
                "instrument_name": "HYPE-PERP",
                "bids": [
                    {"price": 62.672, "size": 20},
                    {"price": 62.671, "size": 15},
                ],
                "asks": [
                    {"price": 62.68, "size": 20},
                    {"price": 62.681, "size": 10},
                ],
                "timestamp": 1_782_716_399_310,
            }
        raise AssertionError(f"Unexpected request: {method} {params}")


def test_symbol_mapping_keeps_requested_hotstuff_markets() -> None:
    assert to_hotstuff_symbol("BTC-PERP") == "BTC-PERP"
    assert to_hotstuff_symbol("ETH-PERP") == "ETH-PERP"
    assert to_hotstuff_symbol("HYPE-PERP") == "HYPE-PERP"
    assert to_hotstuff_symbol("SOL-PERP") == "SOL-PERP"
    assert to_hotstuff_symbol("Silver-PERP") == "SILVER-PERP"
    assert to_hotstuff_symbol("WTIOIL-PERP") == "WTIOIL-PERP"
    assert to_hotstuff_symbol("GOLD-PERP") == "GOLD-PERP"
    assert to_hotstuff_symbol("BRENTOIL-PERP") == "BRENTOIL-PERP"


def test_hotstuff_ticker_lookup_handles_live_value_wrapper() -> None:
    ticker = find_hotstuff_ticker(
        {
            "value": [
                {"symbol": "BTC-PERP"},
                {"symbol": "SILVER-PERP", "mark_price": "58.672"},
            ]
        },
        "SILVER-PERP",
    )

    assert ticker is not None
    assert ticker["mark_price"] == "58.672"


def test_hotstuff_collector_builds_phase1_models() -> None:
    client = FakeHotstuffClient()
    collector = HotstuffPublicCollector(client=client)  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("HYPE-PERP"))

    assert result.snapshot.exchange_id == "Hotstuff"
    assert result.snapshot.symbol == "HYPE-PERP"
    assert result.snapshot.best_bid == 62.672
    assert result.snapshot.best_ask == 62.68
    assert result.snapshot.mark_price == 62.72
    assert result.snapshot.index_price == 62.715991
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.000024]
    assert result.funding_rates[0].next_funding_time.hour == (
        result.funding_rates[0].timestamp.hour + 1
    ) % 24
    assert client.requests[0] == ("ticker", {"symbol": "HYPE-PERP"})
    assert client.requests[1] == ("orderbook", {"symbol": "HYPE-PERP"})
