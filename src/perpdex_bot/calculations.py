from __future__ import annotations

from .models import BookSide, OrderBookLevel, SlippageEstimate, TradeSide


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

