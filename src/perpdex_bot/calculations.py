from __future__ import annotations

from .models import BookSide, OrderBookLevel, OrderSpreadEstimate, SlippageEstimate, TradeSide


def estimate_slippage(
    side: TradeSide,
    notional_usd: float,
    reference_price: float,
    bids: tuple[OrderBookLevel, ...],
    asks: tuple[OrderBookLevel, ...],
) -> SlippageEstimate:
    levels = asks if side == TradeSide.BUY else bids
    expected_side = BookSide.ASK if side == TradeSide.BUY else BookSide.BID
    sorted_levels = sorted(
        (level for level in levels if level.side == expected_side),
        key=lambda level: level.price,
        reverse=side == TradeSide.SELL,
    )

    remaining = notional_usd
    filled_notional = 0.0
    filled_base = 0.0
    for level in sorted_levels:
        take_notional = min(remaining, level.notional)
        if take_notional <= 0:
            break
        filled_notional += take_notional
        filled_base += take_notional / level.price
        remaining -= take_notional
        if remaining <= 1e-9:
            break

    if filled_base == 0:
        return SlippageEstimate(
            side=side,
            notional_usd=notional_usd,
            average_price=None,
            reference_price=reference_price,
            slippage_bps=None,
            filled_notional=0.0,
            complete=False,
        )

    average_price = filled_notional / filled_base
    if side == TradeSide.BUY:
        slippage_bps = (average_price - reference_price) / reference_price * 10_000
    else:
        slippage_bps = (reference_price - average_price) / reference_price * 10_000

    return SlippageEstimate(
        side=side,
        notional_usd=notional_usd,
        average_price=average_price,
        reference_price=reference_price,
        slippage_bps=slippage_bps,
        filled_notional=filled_notional,
        complete=remaining <= 1e-9,
    )


def estimate_slippage_grid(
    notionals: tuple[int, ...],
    reference_price: float,
    bids: tuple[OrderBookLevel, ...],
    asks: tuple[OrderBookLevel, ...],
) -> list[SlippageEstimate]:
    estimates: list[SlippageEstimate] = []
    for side in (TradeSide.BUY, TradeSide.SELL):
        for notional in notionals:
            estimates.append(
                estimate_slippage(
                    side=side,
                    notional_usd=float(notional),
                    reference_price=reference_price,
                    bids=bids,
                    asks=asks,
                )
            )
    return estimates


def estimate_order_spread(
    notional_usd: float,
    reference_price: float,
    bids: tuple[OrderBookLevel, ...],
    asks: tuple[OrderBookLevel, ...],
) -> OrderSpreadEstimate:
    buy = estimate_slippage(
        TradeSide.BUY,
        notional_usd,
        reference_price,
        bids=bids,
        asks=asks,
    )
    sell = estimate_slippage(
        TradeSide.SELL,
        notional_usd,
        reference_price,
        bids=bids,
        asks=asks,
    )
    if buy.average_price is None or sell.average_price is None:
        return OrderSpreadEstimate(
            notional_usd=notional_usd,
            average_buy_price=buy.average_price,
            average_sell_price=sell.average_price,
            spread=None,
            spread_bps=None,
            buy_filled_notional=buy.filled_notional,
            sell_filled_notional=sell.filled_notional,
            complete=False,
        )

    spread = buy.average_price - sell.average_price
    return OrderSpreadEstimate(
        notional_usd=notional_usd,
        average_buy_price=buy.average_price,
        average_sell_price=sell.average_price,
        spread=spread,
        spread_bps=spread / reference_price * 10_000,
        buy_filled_notional=buy.filled_notional,
        sell_filled_notional=sell.filled_notional,
        complete=buy.complete and sell.complete,
    )


def estimate_order_spread_grid(
    notionals: tuple[int, ...],
    reference_price: float,
    bids: tuple[OrderBookLevel, ...],
    asks: tuple[OrderBookLevel, ...],
) -> list[OrderSpreadEstimate]:
    return [
        estimate_order_spread(
            float(notional),
            reference_price=reference_price,
            bids=bids,
            asks=asks,
        )
        for notional in notionals
    ]

