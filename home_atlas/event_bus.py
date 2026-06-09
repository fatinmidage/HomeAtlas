"""Lightweight event bus for post-action hooks with fault-tolerant dispatch."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from home_atlas.models import EventAction

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventAction, int | None, dict[str, Any] | None], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[EventAction | None, list[EventHandler]] = defaultdict(list)

    def subscribe(self, action: EventAction | None, handler: EventHandler) -> None:
        self._handlers[action].append(handler)

    def unsubscribe_all(self) -> None:
        self._handlers.clear()

    def dispatch(self, action: EventAction, item_id: int | None, after: dict[str, Any] | None) -> None:
        for handler in self._handlers.get(action, []):
            try:
                handler(action, item_id, after)
            except Exception:
                logger.warning("EventBus handler %s failed for %s", handler.__name__, action, exc_info=True)
        for handler in self._handlers.get(None, []):
            try:
                handler(action, item_id, after)
            except Exception:
                logger.warning("EventBus wildcard handler %s failed for %s", handler.__name__, action, exc_info=True)


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
