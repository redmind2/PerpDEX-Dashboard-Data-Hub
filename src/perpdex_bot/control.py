from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CONTROL_PATH = Path("data/control.json")


@dataclass(frozen=True)
class CollectorControl:
    collector_paused: bool = False
    paused_exchanges: tuple[str, ...] = ()
    updated_at: str | None = None
    updated_by: str | None = None


def read_control(path: Path = DEFAULT_CONTROL_PATH) -> CollectorControl:
    if not path.exists():
        return CollectorControl()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CollectorControl()
    paused_exchanges = raw.get("paused_exchanges", [])
    if not isinstance(paused_exchanges, list):
        paused_exchanges = []
    return CollectorControl(
        collector_paused=bool(raw.get("collector_paused", False)),
        paused_exchanges=tuple(str(item) for item in paused_exchanges if str(item).strip()),
        updated_at=_optional_str(raw.get("updated_at")),
        updated_by=_optional_str(raw.get("updated_by")),
    )


def write_control(path: Path, control: CollectorControl) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "collector_paused": control.collector_paused,
        "paused_exchanges": list(control.paused_exchanges),
        "updated_at": control.updated_at,
        "updated_by": control.updated_by,
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def pause_all(path: Path, updated_by: str = "telegram") -> CollectorControl:
    control = CollectorControl(
        collector_paused=True,
        paused_exchanges=read_control(path).paused_exchanges,
        updated_at=_now_iso(),
        updated_by=updated_by,
    )
    write_control(path, control)
    return control


def resume_all(path: Path, updated_by: str = "telegram") -> CollectorControl:
    control = CollectorControl(
        collector_paused=False,
        paused_exchanges=(),
        updated_at=_now_iso(),
        updated_by=updated_by,
    )
    write_control(path, control)
    return control


def pause_exchange(path: Path, exchange_id: str, updated_by: str = "telegram") -> CollectorControl:
    current = read_control(path)
    paused = _with_exchange(current.paused_exchanges, exchange_id)
    control = CollectorControl(
        collector_paused=current.collector_paused,
        paused_exchanges=paused,
        updated_at=_now_iso(),
        updated_by=updated_by,
    )
    write_control(path, control)
    return control


def resume_exchange(path: Path, exchange_id: str, updated_by: str = "telegram") -> CollectorControl:
    current = read_control(path)
    paused = tuple(item for item in current.paused_exchanges if item.lower() != exchange_id.lower())
    control = CollectorControl(
        collector_paused=current.collector_paused,
        paused_exchanges=paused,
        updated_at=_now_iso(),
        updated_by=updated_by,
    )
    write_control(path, control)
    return control


def format_control(control: CollectorControl) -> str:
    lines = [
        "PerpDEX collector control",
        f"collector: {'paused' if control.collector_paused else 'running'}",
        f"paused exchanges: {', '.join(control.paused_exchanges) if control.paused_exchanges else 'none'}",
    ]
    if control.updated_at:
        lines.append(f"updated: {control.updated_at}")
    if control.updated_by:
        lines.append(f"updated by: {control.updated_by}")
    return "\n".join(lines)


def _with_exchange(items: tuple[str, ...], exchange_id: str) -> tuple[str, ...]:
    existing = [item for item in items if item.lower() != exchange_id.lower()]
    existing.append(exchange_id)
    return tuple(sorted(existing, key=str.lower))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
