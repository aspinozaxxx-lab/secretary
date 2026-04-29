from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from secretary.config import AppConfig
from secretary.models import TelegramMessage


class ChatArchive:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.root = config.archive.dir or (config.root_dir / "chat_archive")
        self._seen_by_chat: dict[int, set[str]] = {}

    def archive_message(self, message: TelegramMessage) -> bool:
        if not self.config.archive.enabled:
            return False
        chat_dir = self._chat_dir(message)
        chat_dir.mkdir(parents=True, exist_ok=True)
        key = _message_key(message)
        seen = self._seen(message.chat.chat_id, chat_dir / "messages.jsonl")
        if key in seen:
            self._write_index(message, chat_dir)
            return False

        record = _message_record(message)
        _append_text(chat_dir / "messages.jsonl", json.dumps(record, ensure_ascii=False) + "\n")
        if self.config.archive.also_write_markdown:
            _append_text(chat_dir / "messages.md", _markdown_line(message) + "\n")
        seen.add(key)
        self._write_index(message, chat_dir)
        return True

    def describe_for_prompt(self, current_chat_id: int | None = None) -> str:
        if not self.config.archive.enabled:
            return "Lokalnyy arhiv chatov otklyuchen."
        index_path = self.root / "chats_index.json"
        lines = [
            "Lokalnyy arhiv chatov dostupen v read-only sandbox.",
            f"archive_dir: {self.root}",
            f"chats_index: {index_path}",
        ]
        for item in self._index_items():
            prefix = "current_chat" if item.get("chat_id") == current_chat_id else "chat"
            lines.append(
                f"- {prefix}: chat_id={item.get('chat_id')}; title={item.get('chat_title')}; "
                f"type={item.get('chat_type')}; md={item.get('messages_md')}; jsonl={item.get('messages_jsonl')}"
            )
        if len(lines) == 3:
            lines.append("Arhiv poka pust.")
        lines.append("Mozhno chitat eti fayly, esli nuzhno bolshe konteksta. Ne zapisivay v nih.")
        return "\n".join(lines)

    def _chat_dir(self, message: TelegramMessage) -> Path:
        title = message.chat.title or message.chat.username or message.chat.first_name or "chat"
        return self.root / f"{message.chat.chat_id}_{_safe_name(title)}"

    def _seen(self, chat_id: int, jsonl_path: Path) -> set[str]:
        if chat_id in self._seen_by_chat:
            return self._seen_by_chat[chat_id]
        seen: set[str] = set()
        if jsonl_path.exists():
            with jsonl_path.open("r", encoding="utf-8-sig") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    seen.add(f"{item.get('update_id')}:{item.get('message_id')}")
        self._seen_by_chat[chat_id] = seen
        return seen

    def _write_index(self, message: TelegramMessage, chat_dir: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        index_path = self.root / "chats_index.json"
        items = {str(item.get("chat_id")): item for item in self._index_items()}
        items[str(message.chat.chat_id)] = {
            "chat_id": message.chat.chat_id,
            "chat_type": message.chat.chat_type,
            "chat_title": message.chat.title,
            "username": message.chat.username,
            "first_name": message.chat.first_name,
            "last_name": message.chat.last_name,
            "last_seen_at": _date_iso(message.date),
            "last_message_id": message.message_id,
            "dir": str(chat_dir),
            "messages_jsonl": str(chat_dir / "messages.jsonl"),
            "messages_md": str(chat_dir / "messages.md"),
        }
        with index_path.open("w", encoding="utf-8-sig", newline="\n") as stream:
            json.dump(list(items.values()), stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    def _index_items(self) -> list[dict[str, Any]]:
        index_path = self.root / "chats_index.json"
        if not index_path.exists():
            return []
        try:
            with index_path.open("r", encoding="utf-8-sig") as stream:
                loaded = json.load(stream)
        except (json.JSONDecodeError, OSError):
            return []
        return loaded if isinstance(loaded, list) else []


def _message_key(message: TelegramMessage) -> str:
    return f"{message.update_id}:{message.message_id}"


def _message_record(message: TelegramMessage) -> dict[str, Any]:
    sender = message.sender
    return {
        "update_id": message.update_id,
        "message_id": message.message_id,
        "date": _date_iso(message.date),
        "chat_id": message.chat.chat_id,
        "chat_type": message.chat.chat_type,
        "chat_title": message.chat.title,
        "sender_id": sender.user_id if sender else None,
        "sender_username": sender.username if sender else None,
        "sender_name": sender.full_name if sender else None,
        "text": message.text,
        "reply_to_message_id": message.reply_to_message_id,
        "entities": message.entities,
        "mentions": message.mentions,
        "has_attachment": message.has_attachments,
        "attachment_summary": message.attachment_summary,
    }


def _markdown_line(message: TelegramMessage) -> str:
    sender = message.sender.full_name if message.sender else "неизвестно"
    text = message.text or "[нет текста]"
    parts = [f"[{_date_iso(message.date, minute=True)}] {sender}: {text}"]
    if message.reply_to_message_id:
        parts.append(f"(reply_to_message_id={message.reply_to_message_id})")
    if message.has_attachments:
        parts.append(f"(attachment={message.attachment_summary or 'yes'})")
    return " ".join(parts)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().strip(".")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "chat")[:80]


def _date_iso(value: int, minute: bool = False) -> str:
    if not value:
        return ""
    dt = datetime.fromtimestamp(value)
    return dt.strftime("%Y-%m-%d %H:%M") if minute else dt.isoformat(timespec="seconds")


def _append_text(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text("", encoding="utf-8-sig")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
