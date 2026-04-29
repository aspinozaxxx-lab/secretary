from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from threading import RLock
from typing import Callable


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BotEvent:
    timestamp: str
    kind: str
    chat_id: int | None = None
    chat_title: str | None = None
    author: str | None = None
    text: str = ""
    direction: str = "system"
    priority: str | None = None
    reason: str | None = None
    notify: bool | None = None


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[BotEvent], None]] = []
        self._lock = RLock()

    def subscribe(self, callback: Callable[[BotEvent], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[BotEvent], None]) -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item is not callback]

    def publish(self, event: BotEvent) -> None:
        _log_event(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(event)

    def emit(
        self,
        kind: str,
        text: str,
        direction: str | None = None,
        chat_id: int | None = None,
        chat_title: str | None = None,
        author: str | None = None,
        priority: str | None = None,
        reason: str | None = None,
        notify: bool | None = None,
    ) -> None:
        self.publish(
            BotEvent(
                timestamp=datetime.now().isoformat(timespec="seconds"),
                kind=kind,
                chat_id=chat_id,
                chat_title=chat_title,
                author=author,
                text=text,
                direction=direction or kind,
                priority=priority,
                reason=reason,
                notify=notify,
            )
        )


def emit_if_present(event_bus: EventBus | None, kind: str, text: str, **kwargs: object) -> None:
    if event_bus is not None:
        event_bus.emit(kind, text, **kwargs)


def _log_event(event: BotEvent) -> None:
    message = (
        "event kind=%s direction=%s chat_id=%s chat=%s author=%s notify=%s priority=%s reason=%s text=%s"
    )
    args = (
        event.kind,
        event.direction,
        event.chat_id,
        event.chat_title,
        event.author,
        event.notify,
        event.priority,
        event.reason,
        event.text,
    )
    if event.kind == "error":
        LOGGER.error(message, *args)
    else:
        LOGGER.info(message, *args)
