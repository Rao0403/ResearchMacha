from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("research_macha.fallbacks")

_fallback_events: ContextVar[list[dict[str, Any]]] = ContextVar("fallback_events", default=[])


def clear_fallback_events() -> None:
    _fallback_events.set([])


def record_fallback(
    component: str,
    fallback: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    event = {
        "component": component,
        "fallback": fallback,
        "reason": reason[:1000],
        "metadata": metadata or {},
    }
    current_events = list(_fallback_events.get())
    current_events.append(event)
    _fallback_events.set(current_events)
    logger.warning("Fallback used: %s -> %s: %s", component, fallback, reason)


def pop_fallback_events() -> list[dict[str, Any]]:
    events = list(_fallback_events.get())
    _fallback_events.set([])
    return events
