from __future__ import annotations

import logging
import re
from typing import Any

import requests

from secretary.events import EventBus, emit_if_present
from secretary.models import TelegramChat, TelegramMessage, TelegramUser

LOGGER = logging.getLogger(__name__)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,32})")


class TelegramClient:
    def __init__(self, bot_token: str, timeout_seconds: int = 35, event_bus: EventBus | None = None) -> None:
        self.bot_token = bot_token
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.event_bus = event_bus

    def get_updates(self, offset: int | None, timeout: int = 1) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "edited_message"],
        }
        if offset is not None:
            payload["offset"] = offset
        response = requests.post(
            f"{self.base_url}/getUpdates",
            json=payload,
            timeout=timeout + 2,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")
        return list(data.get("result", []))

    def get_webhook_info(self) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/getWebhookInfo",
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getWebhookInfo failed: {data}")
        return dict(data.get("result") or {})

    def delete_webhook(self) -> None:
        response = requests.post(
            f"{self.base_url}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram deleteWebhook failed: {data}")

    def set_my_commands(
        self,
        commands: list[dict[str, str]],
        scope: dict[str, Any] | None = None,
        language_code: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"commands": commands}
        if scope is not None:
            payload["scope"] = scope
        if language_code:
            payload["language_code"] = language_code
        response = requests.post(
            f"{self.base_url}/setMyCommands",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram setMyCommands failed: {data}")

    def get_my_commands(
        self,
        scope: dict[str, Any] | None = None,
        language_code: str | None = None,
    ) -> list[dict[str, str]]:
        payload: dict[str, Any] = {}
        if scope is not None:
            payload["scope"] = scope
        if language_code:
            payload["language_code"] = language_code
        response = requests.post(
            f"{self.base_url}/getMyCommands",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getMyCommands failed: {data}")
        return list(data.get("result") or [])

    def delete_my_commands(
        self,
        scope: dict[str, Any] | None = None,
        language_code: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if scope is not None:
            payload["scope"] = scope
        if language_code:
            payload["language_code"] = language_code
        response = requests.post(
            f"{self.base_url}/deleteMyCommands",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram deleteMyCommands failed: {data}")

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        disable_web_page_preview: bool = True,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        response = requests.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")
        emit_if_present(
            self.event_bus,
            "outgoing",
            text,
            direction="outgoing",
            chat_id=chat_id,
        )


def parse_update(update: dict[str, Any]) -> TelegramMessage | None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None

    text = str(message.get("text") or message.get("caption") or "")
    raw_text = text
    command = _extract_command(text)
    chat_raw = message.get("chat") or {}
    sender_raw = message.get("from") or {}
    reply_raw = message.get("reply_to_message") or {}
    reply_user = reply_raw.get("from") or {}

    attachment_keys = [
        key
        for key in (
            "photo",
            "video",
            "document",
            "audio",
            "voice",
            "sticker",
            "animation",
            "poll",
            "location",
            "contact",
        )
        if key in message
    ]
    has_attachments = bool(attachment_keys)
    entities = list(message.get("entities") or message.get("caption_entities") or [])
    reply_to_message_id = reply_raw.get("message_id")

    sender = None
    if sender_raw:
        sender = TelegramUser(
            user_id=sender_raw.get("id"),
            username=sender_raw.get("username"),
            full_name=_full_name(sender_raw),
            is_bot=bool(sender_raw.get("is_bot")),
        )

    return TelegramMessage(
        update_id=int(update.get("update_id")),
        message_id=int(message.get("message_id")),
        date=int(message.get("date", 0)),
        chat=TelegramChat(
            chat_id=int(chat_raw.get("id")),
            chat_type=str(chat_raw.get("type", "")),
            title=chat_raw.get("title") or chat_raw.get("first_name"),
            username=chat_raw.get("username"),
            first_name=chat_raw.get("first_name"),
            last_name=chat_raw.get("last_name"),
        ),
        sender=sender,
        text=text.strip(),
        raw_text=raw_text,
        has_attachments=has_attachments,
        attachment_summary=", ".join(attachment_keys),
        is_command=command is not None,
        command=command,
        mentions=[item.lower() for item in MENTION_RE.findall(text)],
        entities=entities,
        reply_to_user_id=reply_user.get("id"),
        reply_to_message_id=reply_to_message_id,
        reply_to_username=reply_user.get("username"),
        reply_to_text=reply_raw.get("text"),
        raw=message,
    )


def _extract_command(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    first = text.split(maxsplit=1)[0]
    command = first.split("@", maxsplit=1)[0]
    return command.lower()


def _full_name(user: dict[str, Any]) -> str:
    parts = [str(user.get("first_name", "")).strip(), str(user.get("last_name", "")).strip()]
    full_name = " ".join(part for part in parts if part)
    return full_name or str(user.get("username") or user.get("id") or "unknown")
