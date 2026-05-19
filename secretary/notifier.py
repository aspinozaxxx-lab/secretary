from __future__ import annotations

import logging
from collections.abc import Callable

from secretary.config import TelegramConfig
from secretary.events import EventBus, emit_if_present
from secretary.models import DecisionResult, TelegramMessage
from secretary.preferences import normalize_communication_tone
from secretary.telegram_client import TelegramClient

LOGGER = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        client: TelegramClient,
        config: TelegramConfig,
        event_bus: EventBus | None = None,
        get_communication_tone: Callable[[], str] | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.event_bus = event_bus
        self.get_communication_tone = get_communication_tone

    def target_chat_id(self) -> int | None:
        return self.config.notify_chat_id or self.config.notify_user_id

    def notify(self, message: TelegramMessage, decision: DecisionResult) -> None:
        target_chat_id = self.target_chat_id()
        if target_chat_id is None:
            LOGGER.warning("notify_chat_id/notify_user_id is not configured; notification skipped")
            emit_if_present(self.event_bus, "error", "Не задан notify_chat_id/notify_user_id", direction="error")
            return
        emit_if_present(
            self.event_bus,
            "system",
            "Отправка уведомления",
            direction="system",
            chat_id=message.chat.chat_id,
            chat_title=message.chat.title,
            priority=decision.priority,
            reason=decision.reason,
            notify=decision.notify,
        )
        try:
            self.client.send_message(target_chat_id, _format_notification(message, decision, self._tone()))
        except Exception as exc:
            LOGGER.exception("Notification failed")
            emit_if_present(self.event_bus, "error", f"Не удалось отправить уведомление: {exc}", direction="error")
            return
        emit_if_present(
            self.event_bus,
            "system",
            "Уведомление отправлено",
            direction="system",
            chat_id=target_chat_id,
            priority=decision.priority,
            reason=decision.reason,
            notify=decision.notify,
        )

    def send_test_notification(self, text: str) -> tuple[bool, str]:
        target_chat_id = self.target_chat_id()
        if target_chat_id is None:
            return False, "Не задан notify_chat_id/notify_user_id."
        emit_if_present(self.event_bus, "system", "Отправка тестового уведомления", direction="system")
        try:
            self.client.send_message(target_chat_id, text)
        except Exception as exc:
            LOGGER.exception("Test notification failed")
            emit_if_present(self.event_bus, "error", f"Тестовое уведомление не отправлено: {exc}", direction="error")
            return False, str(exc)
        emit_if_present(self.event_bus, "system", "Тестовое уведомление отправлено", direction="system")
        return True, "Тестовое уведомление отправлено."

    def _tone(self) -> str:
        if self.get_communication_tone is None:
            return normalize_communication_tone(None)
        return normalize_communication_tone(self.get_communication_tone())


def _format_notification(message: TelegramMessage, decision: DecisionResult, tone: str | None = None) -> str:
    sender = "неизвестно"
    if message.sender:
        sender = message.sender.full_name
        if message.sender.username:
            sender = f"{sender} (@{message.sender.username})"
    chat = message.chat.title or str(message.chat.chat_id)
    summary = _clean_sentence(decision.summary) or _clean_sentence(message.text) or "появилось сообщение без текста"
    action = _clean_sentence(decision.suggested_action)
    reason = _clean_sentence(decision.reason)
    tone_text = normalize_communication_tone(tone).lower()

    first_line = f"{sender} в «{chat}»: {summary}"
    if "официаль" not in tone_text:
        first_line = first_line.replace("необходимо", "нужно").replace("следует", "лучше")

    parts = [first_line]
    if action:
        parts.append(action)
    elif reason:
        parts.append(reason)
    joined = " ".join(parts).lower()
    if (
        decision.priority in {"urgent", "high"}
        and "сроч" not in joined
        and "сейчас" not in joined
        and "лучше посмотреть" not in joined
    ):
        parts.append("Лучше посмотреть сейчас.")

    link = _message_link(message)
    if link:
        parts.append("")
        parts.append(link)
    if decision.classification_error:
        parts.append("")
        parts.append("Я не уверен в классификации, проверь вручную.")
    return "\n".join(parts)


def _clean_sentence(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _message_link(message: TelegramMessage) -> str | None:
    if message.chat.username:
        return f"https://t.me/{message.chat.username}/{message.message_id}"
    chat_id = str(message.chat.chat_id)
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message.message_id}"
    return None
