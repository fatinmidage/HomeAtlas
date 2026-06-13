"""Lightweight event bus for post-action hooks with fault-tolerant dispatch."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.orm import Session as SASession

from home_atlas.domain.models import EventAction

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
_PENDING_EVENTS_KEY = "home_atlas_pending_events"


def get_event_bus() -> EventBus:
    return _bus


def enqueue_event(session: SASession, action: EventAction, item_id: int | None, after: dict[str, Any] | None) -> None:
    pending = session.info.setdefault(_PENDING_EVENTS_KEY, [])
    pending.append((action, item_id, after))


@event.listens_for(SASession, "after_commit")
def _dispatch_pending_events(session: SASession) -> None:
    pending = session.info.pop(_PENDING_EVENTS_KEY, [])
    for action, item_id, after in pending:
        get_event_bus().dispatch(action, item_id, after)


@event.listens_for(SASession, "after_rollback")
def _clear_pending_events(session: SASession) -> None:
    session.info.pop(_PENDING_EVENTS_KEY, None)
