from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from requests import HTTPError, ReadTimeout, RequestException

from secretary.batching import split_message_batches
from secretary.archive import ChatArchive
from secretary.database import ChatDatabase
from secretary.decision_engine import DecisionEngine
from secretary.events import EventBus, emit_if_present
from secretary.models import DecisionResult, TelegramMessage
from secretary.notifier import Notifier
from secretary.state import StateStore
from secretary.telegram_client import TelegramClient, parse_update

LOGGER = logging.getLogger(__name__)


class PollingLoop:
    def __init__(
        self,
        client: TelegramClient,
        state: StateStore,
        decision_engine: DecisionEngine,
        notifier: Notifier,
        is_allowed_message: Callable[[TelegramMessage], bool],
        handle_command: Callable[[TelegramMessage], bool],
        handle_document: Callable[[TelegramMessage], bool],
        handle_private_text: Callable[[TelegramMessage], bool],
        check_scheduled_tasks: Callable[[], None] | None = None,
        event_bus: EventBus | None = None,
        archive: ChatArchive | None = None,
        database: ChatDatabase | None = None,
    ) -> None:
        self.client = client
        self.state = state
        self.decision_engine = decision_engine
        self.notifier = notifier
        self.is_allowed_message = is_allowed_message
        self.handle_command = handle_command
        self.handle_document = handle_document
        self.handle_private_text = handle_private_text
        self.check_scheduled_tasks = check_scheduled_tasks
        self.event_bus = event_bus
        self.archive = archive
        self.database = database
        self.running = True
        self._stop_event = threading.Event()
        self._last_conflict_log_at = 0.0

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()

    def run_forever(self) -> None:
        LOGGER.info("Polling started")
        emit_if_present(self.event_bus, "system", "Polling started", direction="system")
        while self.running and not self._stop_event.is_set():
            try:
                if self.check_scheduled_tasks is not None:
                    self.check_scheduled_tasks()
                updates = self.client.get_updates(self.state.next_offset, timeout=1)
                if not updates:
                    continue
                self._process_updates(updates)
                self.state.save()
            except HTTPError as exc:
                if _is_telegram_conflict(exc):
                    now = time.monotonic()
                    if now - self._last_conflict_log_at > 60:
                        LOGGER.error(
                            "Похоже, запущен второй экземпляр бота или активен другой getUpdates/webhook"
                        )
                        emit_if_present(
                            self.event_bus,
                            "error",
                            "Похоже, запущен второй экземпляр бота или активен другой getUpdates/webhook",
                            direction="error",
                        )
                        self._last_conflict_log_at = now
                    self._stop_event.wait(15)
                    continue
                LOGGER.error("Telegram request failed: %s", exc)
                emit_if_present(self.event_bus, "error", f"Telegram request failed: {exc}", direction="error")
                self._stop_event.wait(5)
            except ReadTimeout:
                LOGGER.debug("Telegram long polling read timeout")
                continue
            except RequestException as exc:
                LOGGER.error("Telegram request failed: %s", exc)
                emit_if_present(self.event_bus, "error", f"Telegram request failed: {exc}", direction="error")
                self._stop_event.wait(5)
            except Exception:
                LOGGER.exception("Unexpected polling error")
                emit_if_present(self.event_bus, "error", "Unexpected polling error", direction="error")
                self._stop_event.wait(5)
        LOGGER.info("Polling stopped")
        emit_if_present(self.event_bus, "system", "Polling stopped", direction="system")

    def _process_updates(self, updates: list[dict]) -> None:
        messages_to_analyze: list[TelegramMessage] = []
        for update in updates:
            if self._stop_event.is_set():
                break
            update_id = int(update.get("update_id"))
            try:
                message = parse_update(update)
                if message is None:
                    continue
                self.state.update_chat(message)
                if self.archive is not None:
                    archived = self.archive.archive_message(message)
                    if archived:
                        emit_if_present(
                            self.event_bus,
                            "system",
                            "Сообщение добавлено в локальный архив",
                            direction="system",
                            chat_id=message.chat.chat_id,
                            chat_title=message.chat.title,
                            author=_message_author(message),
                        )
                if self.database is not None:
                    try:
                        self.database.insert_telegram_message(message)
                    except Exception:
                        LOGGER.exception("SQLite message save failed")
                        emit_if_present(
                            self.event_bus,
                            "error",
                            "Не удалось записать сообщение в SQLite",
                            direction="error",
                            chat_id=message.chat.chat_id,
                            chat_title=message.chat.title,
                            author=_message_author(message),
                        )
                emit_if_present(
                    self.event_bus,
                    "incoming",
                    message.text or "[вложение без текста]",
                    direction="incoming",
                    chat_id=message.chat.chat_id,
                    chat_title=message.chat.title,
                    author=_message_author(message),
                )
                if not self.is_allowed_message(message):
                    LOGGER.info("Ignoring message from disallowed chat_id=%s", message.chat.chat_id)
                    continue
                if message.has_attachments and not message.text:
                    LOGGER.info(
                        "Message with attachment ignored: chat_id=%s message_id=%s",
                        message.chat.chat_id,
                        message.message_id,
                    )
                if message.text:
                    self.state.add_message(message)
                if message.is_command and self.handle_command(message):
                    continue
                if message.document_file_id and self.handle_document(message):
                    continue
                if self.handle_private_text(message):
                    continue
                if message.text:
                    messages_to_analyze.append(message)
            finally:
                self.state.mark_update_seen(update_id)

        if not messages_to_analyze or self._stop_event.is_set():
            return

        if not self.decision_engine.config.decision.batch_enabled:
            for message in messages_to_analyze:
                history = self.state.get_history(message.chat.chat_id, limit=self.state.history_limit_per_chat)
                decision = self.decision_engine.decide(message, history)
                self._handle_decision(message, decision)
            return

        decision_config = self.decision_engine.config.decision
        batches = split_message_batches(
            messages_to_analyze,
            max_messages=decision_config.batch_max_messages,
            max_chars=decision_config.batch_max_chars,
            max_age_seconds=decision_config.batch_max_age_seconds,
        )
        for batch in batches:
            if self._stop_event.is_set():
                break
            self._process_message_batch(batch)

    def _process_message_batch(self, batch: list[TelegramMessage]) -> None:
        if not batch:
            return
        first = batch[0]
        batch_chars = sum(len(message.text or "") for message in batch)
        emit_if_present(
            self.event_bus,
            "system",
            f"Batch started: {len(batch)} сообщений, {batch_chars} символов",
            direction="system",
            chat_id=first.chat.chat_id,
            chat_title=first.chat.title,
        )
        history = self.state.get_history_before(
            first.chat.chat_id,
            before_message_id=first.message_id,
            limit=min(self.state.history_limit_per_chat, 100),
        )
        result = self.decision_engine.analyze_message_batch(batch, history)
        if result.need_more_context and result.context_request is not None:
            request = result.context_request
            chat_id = request.chat_id or first.chat.chat_id
            before_message_id = request.before_message_id or first.message_id
            LOGGER.info(
                "Codex requested more context: chat_id=%s before_message_id=%s limit=%s keywords=%s",
                chat_id,
                before_message_id,
                request.limit,
                request.keywords,
            )
            emit_if_present(
                self.event_bus,
                "system",
                "Codex запросил дополнительный контекст",
                direction="system",
                chat_id=first.chat.chat_id,
                chat_title=first.chat.title,
            )
            if self.database is not None:
                additional_context = self.database.get_messages_around(
                    chat_id,
                    before_message_id=before_message_id,
                    limit=request.limit,
                )
            else:
                additional_context = self.state.get_history_before(
                    chat_id,
                    before_message_id=before_message_id,
                    limit=request.limit,
                    keywords=request.keywords,
                )
            note = (
                "Dopolnitelnyy kontekst iz lokalnoy istorii:"
                if additional_context
                else "Dopolnitelnogo konteksta v lokalnoy istorii net."
            )
            emit_if_present(
                self.event_bus,
                "system",
                f"Дополнительный контекст: {'найден' if additional_context else 'не найден'}",
                direction="system",
                chat_id=first.chat.chat_id,
                chat_title=first.chat.title,
            )
            result = self.decision_engine.analyze_message_batch(
                batch,
                history,
                additional_context=additional_context,
                additional_context_note=note,
            )
        if result.batch_summary:
            emit_if_present(
                self.event_bus,
                "system",
                f"Batch summary: {result.batch_summary}",
                direction="system",
                chat_id=first.chat.chat_id,
                chat_title=first.chat.title,
            )
        for message in batch:
            decision = result.items.get(
                message.message_id,
                DecisionResult.no_notify("Codex не дал решение по сообщению.", source="codex"),
            )
            self._handle_decision(message, decision)
        emit_if_present(
            self.event_bus,
            "system",
            f"Batch finished: {len(batch)} сообщений",
            direction="system",
            chat_id=first.chat.chat_id,
            chat_title=first.chat.title,
        )

    def _handle_decision(self, message: TelegramMessage, decision: DecisionResult) -> None:
        LOGGER.info(
            "Decision chat_id=%s message_id=%s notify=%s confidence=%.2f source=%s",
            message.chat.chat_id,
            message.message_id,
            decision.notify,
            decision.confidence,
            decision.source,
        )
        emit_if_present(
            self.event_bus,
            "decision",
            message.text,
            direction="system",
            chat_id=message.chat.chat_id,
            chat_title=message.chat.title,
            author=_message_author(message),
            priority=decision.priority,
            reason=decision.reason,
            notify=decision.notify,
        )
        if decision.notify:
            emit_if_present(
                self.event_bus,
                "system",
                "Decision notify=true, вызываю notifier",
                direction="system",
                chat_id=message.chat.chat_id,
                chat_title=message.chat.title,
                priority=decision.priority,
                reason=decision.reason,
                notify=True,
            )
            self.notifier.notify(message, decision)


def _is_telegram_conflict(exc: HTTPError) -> bool:
    response = getattr(exc, "response", None)
    return response is not None and response.status_code == 409


def _message_author(message: TelegramMessage) -> str | None:
    if not message.sender:
        return None
    if message.sender.username:
        return f"{message.sender.full_name} (@{message.sender.username})"
    return message.sender.full_name
