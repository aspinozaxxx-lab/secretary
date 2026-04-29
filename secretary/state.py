from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from secretary.models import ChatHistoryEntry, TelegramMessage


class StateStore:
    def __init__(self, path: Path, history_limit_per_chat: int) -> None:
        self.path = path
        self.history_limit_per_chat = history_limit_per_chat
        self.data: dict[str, Any] = {
            "last_update_id": None,
            "chats": {},
            "last_summary_sent": {},
        }

    def load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8-sig") as stream:
            loaded = json.load(stream)
        if isinstance(loaded, dict):
            self.data.update(loaded)
        self.data.setdefault("chats", {})
        self.data.setdefault("last_summary_sent", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="\n") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temp_path.replace(self.path)

    @property
    def last_update_id(self) -> int | None:
        value = self.data.get("last_update_id")
        return int(value) if value is not None else None

    @property
    def next_offset(self) -> int | None:
        last_update_id = self.last_update_id
        if last_update_id is None:
            return None
        return last_update_id + 1

    def mark_update_seen(self, update_id: int) -> None:
        current = self.last_update_id
        if current is None or update_id > current:
            self.data["last_update_id"] = update_id

    def update_chat(self, message: TelegramMessage) -> None:
        chat_key = str(message.chat.chat_id)
        chats = self.data.setdefault("chats", {})
        chat_data = chats.setdefault(
            chat_key,
            {
                "chat_id": message.chat.chat_id,
                "history": [],
            },
        )
        chat_data["chat_id"] = message.chat.chat_id
        chat_data["type"] = message.chat.chat_type
        chat_data["title"] = message.chat.title
        chat_data["chat_title"] = message.chat.title
        chat_data["username"] = message.chat.username
        chat_data["first_name"] = message.chat.first_name
        chat_data["last_name"] = message.chat.last_name
        chat_data["last_seen_at"] = _format_ts(message.date)
        chat_data["last_message_id"] = message.message_id

    def add_message(self, message: TelegramMessage) -> None:
        if not message.text:
            return
        self.update_chat(message)
        chat_key = str(message.chat.chat_id)
        chats = self.data.setdefault("chats", {})
        chat_data = chats.setdefault(
            chat_key,
            {
                "chat_id": message.chat.chat_id,
                "chat_title": message.chat.title,
                "history": [],
            },
        )
        chat_data["chat_title"] = message.chat.title

        sender = "unknown"
        if message.sender:
            sender = message.sender.full_name
            if message.sender.username:
                sender = f"{sender} (@{message.sender.username})"

        entry = ChatHistoryEntry(
            chat_id=message.chat.chat_id,
            chat_title=message.chat.title,
            sender=sender,
            text=message.text,
            date=message.date,
            message_id=message.message_id,
        )
        history = chat_data.setdefault("history", [])
        if not any(item.get("message_id") == message.message_id for item in history):
            history.append(asdict(entry))
        del history[:-self.history_limit_per_chat]

    def get_history(self, chat_id: int, limit: int | None = None) -> list[ChatHistoryEntry]:
        chat_data = self.data.get("chats", {}).get(str(chat_id), {})
        raw_history = chat_data.get("history", [])
        selected = raw_history[-limit:] if limit else raw_history
        result: list[ChatHistoryEntry] = []
        for item in selected:
            result.append(
                ChatHistoryEntry(
                    chat_id=int(item.get("chat_id", chat_id)),
                    chat_title=item.get("chat_title"),
                    sender=str(item.get("sender", "unknown")),
                    text=str(item.get("text", "")),
                    date=int(item.get("date", 0)),
                    message_id=int(item.get("message_id", 0)),
                )
            )
        return result

    def get_history_before(
        self,
        chat_id: int,
        before_message_id: int | None,
        limit: int,
        keywords: list[str] | None = None,
    ) -> list[ChatHistoryEntry]:
        limit = max(1, min(int(limit), 100))
        entries = self.get_history(chat_id)
        if before_message_id is not None:
            entries = [entry for entry in entries if entry.message_id < before_message_id]
        entries.sort(key=lambda item: item.message_id, reverse=True)
        if keywords:
            relevant = [entry for entry in entries if _matches_keywords_list(entry, keywords)]
            if relevant:
                selected = relevant[:limit]
                selected.sort(key=lambda item: item.message_id)
                return selected
        selected = entries[:limit]
        selected.sort(key=lambda item: item.message_id)
        return selected

    def get_recent_messages(
        self,
        limit: int,
        question: str | None = None,
        include_private: bool = False,
    ) -> list[ChatHistoryEntry]:
        entries: list[ChatHistoryEntry] = []
        for chat_data in self.data.get("chats", {}).values():
            if not include_private and chat_data.get("type") == "private":
                continue
            for item in chat_data.get("history", []):
                entries.append(
                    ChatHistoryEntry(
                        chat_id=int(item.get("chat_id", chat_data.get("chat_id", 0))),
                        chat_title=item.get("chat_title") or chat_data.get("title"),
                        sender=str(item.get("sender", "unknown")),
                        text=str(item.get("text", "")),
                        date=int(item.get("date", 0)),
                        message_id=int(item.get("message_id", 0)),
                    )
                )
        entries.sort(key=lambda item: item.date, reverse=True)
        keywords = _keywords(question or "")
        if keywords:
            relevant = [entry for entry in entries if _matches_keywords(entry, keywords)]
            if len(relevant) >= max(5, min(limit, 10)):
                return relevant[:limit]
            mixed = relevant[:]
            seen = {(entry.chat_id, entry.message_id) for entry in mixed}
            for entry in entries:
                key = (entry.chat_id, entry.message_id)
                if key not in seen:
                    mixed.append(entry)
                    seen.add(key)
                if len(mixed) >= limit:
                    break
            return mixed[:limit]
        return entries[:limit]

    def get_recent_messages_since(
        self,
        since_ts: int,
        limit: int,
        include_private: bool = False,
    ) -> list[ChatHistoryEntry]:
        entries = self.get_recent_messages(limit=max(limit * 3, limit), include_private=include_private)
        selected = [entry for entry in entries if entry.date >= since_ts]
        selected.sort(key=lambda item: item.date)
        return selected[-limit:]

    def get_last_summary_sent(self, schedule_time: str) -> str | None:
        value = self.data.setdefault("last_summary_sent", {}).get(schedule_time)
        return str(value) if value else None

    def mark_summary_sent(self, schedule_time: str, date_key: str) -> None:
        self.data.setdefault("last_summary_sent", {})[schedule_time] = date_key

    def known_chats_count(self) -> int:
        return len(self.data.get("chats", {}))

    def list_chats(self, limit: int = 30) -> list[dict[str, Any]]:
        chats = list(self.data.get("chats", {}).values())
        chats.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
        return chats[:limit]


def _format_ts(value: int) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _keywords(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    ignored = {
        "что",
        "где",
        "как",
        "кто",
        "это",
        "было",
        "были",
        "сегодня",
        "важного",
        "важное",
        "проекту",
        "проект",
        "по",
        "на",
        "за",
        "и",
        "в",
        "с",
        "the",
        "and",
        "for",
    }
    result = []
    for item in cleaned.split():
        if len(item) >= 3 and item not in ignored:
            result.append(item)
    return result[:12]


def _matches_keywords(entry: ChatHistoryEntry, keywords: list[str]) -> bool:
    haystack = f"{entry.chat_title or ''} {entry.sender} {entry.text}".lower()
    return any(keyword in haystack for keyword in keywords)


def _matches_keywords_list(entry: ChatHistoryEntry, keywords: list[str]) -> bool:
    haystack = f"{entry.chat_title or ''} {entry.sender} {entry.text}".lower()
    return any(str(keyword).lower() in haystack for keyword in keywords if str(keyword).strip())
