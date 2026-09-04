from __future__ import annotations

from typing import Any


def new_log() -> list[dict[str, Any]]:
    return []


def add(log: list[dict[str, Any]], event_type: str, **detail: Any) -> None:
    log.append({"type": event_type, "detail": detail})
