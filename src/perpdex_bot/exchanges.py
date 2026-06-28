from __future__ import annotations

from collections.abc import Callable

from .collectors import LivePublicCollector, PublicAPISettings
from .hibachi import HibachiPublicCollector
from .rise import RisePublicCollector


CollectorFactory = Callable[[PublicAPISettings], LivePublicCollector]


def _hibachi(settings: PublicAPISettings) -> LivePublicCollector:
    collector = HibachiPublicCollector()
    collector.client.settings = settings
    return collector


def _rise(settings: PublicAPISettings) -> LivePublicCollector:
    collector = RisePublicCollector()
    collector.client.settings = settings
    return collector


PUBLIC_COLLECTOR_FACTORIES: dict[str, CollectorFactory] = {
    "hibachi": _hibachi,
    "rise": _rise,
    "risex": _rise,
}


def supported_public_exchanges() -> tuple[str, ...]:
    return tuple(
        factory(PublicAPISettings()).exchange_id
        for factory in PUBLIC_COLLECTOR_FACTORIES.values()
    )


def create_public_collector(exchange_id: str, settings: PublicAPISettings) -> LivePublicCollector:
    factory = PUBLIC_COLLECTOR_FACTORIES.get(exchange_id.lower())
    if factory is None:
        choices = ", ".join(supported_public_exchanges())
        raise ValueError(f"Unsupported public exchange: {exchange_id}. Supported: {choices}")
    return factory(settings)
