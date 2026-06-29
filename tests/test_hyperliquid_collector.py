from __future__ import annotations

import asyncio

from perpdex_bot.hyperliquid import (
    HyperliquidPublicCollector,
    find_hyperliquid_context,
    to_hyperliquid_market,
)


class FakeHyperliquidClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def post_info(self, payload: dict[str, object]):
        self.requests.append(payload)
        if payload["type"] == "metaAndAssetCtxs":
            assert payload == {"type": "metaAndAssetCtxs", "dex": "xyz"}
            return [
                {
                    "universe": [
                        {"name": "xyz:SMSN"},
                        {"name": "xyz:SKHX"},
                    ]
                },
                [
                    {
                        "funding": "0.0000125",
                        "markPx": "210.45",
                        "midPx": "210.43",
                        "oraclePx": "210.40",
                    },
                    {
                        "funding": "0.0000100",
                        "markPx": "1705.0",
                        "midPx": "1704.95",
                        "oraclePx": "1704.80",
                    },
                ],
            ]
        if payload["type"] == "l2Book":
            assert payload == {"type": "l2Book", "coin": "xyz:SMSN"}
            return {
                "coin": "xyz:SMSN",
                "time": 1_782_717_008_710,
                "levels": [
                    [
                        {"px": "210.39", "sz": "4.587", "n": 2},
                        {"px": "210.38", "sz": "1.0", "n": 1},
                    ],
                    [
                        {"px": "210.47", "sz": "0.838", "n": 1},
                        {"px": "210.48", "sz": "2.0", "n": 1},
                    ],
                ],
            }
        raise AssertionError(f"Unexpected payload: {payload}")


def test_hyperliquid_symbol_mapping() -> None:
    assert to_hyperliquid_market("BTC-PERP").coin == "BTC"
    assert to_hyperliquid_market("HYPE-PERP").coin == "HYPE"
    assert to_hyperliquid_market("SAMSUNG-PERP").coin == "xyz:SMSN"
    assert to_hyperliquid_market("SAMSUNG-PERP").dex == "xyz"
    assert to_hyperliquid_market("SKHYNICS-PERP").coin == "xyz:SKHX"
    assert to_hyperliquid_market("WTIOIL-PERP").coin == "cash:WTI"


def test_hyperliquid_context_lookup_uses_aligned_universe_index() -> None:
    context = find_hyperliquid_context(
        [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
            [{"markPx": "60000"}, {"markPx": "1580"}],
        ],
        "ETH",
    )

    assert context is not None
    assert context["markPx"] == "1580"


def test_hyperliquid_collector_builds_phase1_models() -> None:
    client = FakeHyperliquidClient()
    collector = HyperliquidPublicCollector(client=client)  # type: ignore[arg-type]

    result = asyncio.run(collector.collect_once("SAMSUNG-PERP"))

    assert result.snapshot.exchange_id == "Hyperliquid"
    assert result.snapshot.symbol == "SAMSUNG-PERP"
    assert result.snapshot.best_bid == 210.39
    assert result.snapshot.best_ask == 210.47
    assert result.snapshot.mark_price == 210.45
    assert result.snapshot.index_price == 210.40
    assert len(result.snapshot.bids) == 2
    assert len(result.snapshot.asks) == 2
    assert [item.rate for item in result.funding_rates] == [0.0000125]
    assert client.requests[0] == {"type": "metaAndAssetCtxs", "dex": "xyz"}
    assert client.requests[1] == {"type": "l2Book", "coin": "xyz:SMSN"}
