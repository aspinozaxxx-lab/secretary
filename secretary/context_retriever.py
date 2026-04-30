from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from secretary.config import AppConfig
from secretary.database import ChatDatabase
from secretary.models import TelegramMessage


class ContextRetriever:
    def __init__(self, config: AppConfig, database: ChatDatabase | None) -> None:
        self.config = config
        self.database = database

    def for_message(self, message: TelegramMessage, max_chars: int = 12000) -> str:
        if self.database is None:
            return "SQLite baza istorii ne podklyuchena."
        query = " ".join([message.chat.title or "", message.text or ""])
        keywords = self._keywords(query)
        targeted = self._targeted_chats(keywords, current_chat_id=message.chat.chat_id)
        chat_ids = [int(chat["chat_id"]) for chat in targeted] or [message.chat.chat_id]
        recent = self.database.get_recent_messages(limit=40, chat_ids=chat_ids, include_private=False)
        hits = self.database.search_messages(message.text or query, limit=30, chat_ids=chat_ids)
        return self.database.export_context_for_codex(
            title="SQLite context for current message:",
            targeted_chats=targeted,
            recent_messages=recent,
            search_hits=hits,
            max_chars=max_chars,
        )

    def for_batch(self, messages: list[TelegramMessage], max_chars: int = 14000) -> str:
        if self.database is None or not messages:
            return "SQLite baza istorii ne podklyuchena."
        first = messages[0]
        query = " ".join([first.chat.title or "", " ".join(message.text or "" for message in messages)])
        keywords = self._keywords(query)
        targeted = self._targeted_chats(keywords, current_chat_id=first.chat.chat_id)
        chat_ids = [int(chat["chat_id"]) for chat in targeted] or [first.chat.chat_id]
        recent = self.database.get_recent_messages(limit=60, chat_ids=chat_ids, include_private=False)
        hits = self.database.search_messages(query, limit=40, chat_ids=chat_ids)
        return self.database.export_context_for_codex(
            title="SQLite context for batch decision:",
            targeted_chats=targeted,
            recent_messages=recent,
            search_hits=hits,
            max_chars=max_chars,
        )

    def for_question(self, question: str, max_messages: int, max_chars: int = 18000) -> str:
        if self.database is None:
            return "SQLite baza istorii ne podklyuchena."
        keywords = self._keywords(question)
        targeted = self._targeted_chats(keywords)
        chat_ids = [int(chat["chat_id"]) for chat in targeted] or None
        hits = self.database.search_messages(question, limit=max_messages, chat_ids=chat_ids)
        recent_limit = max(20, max_messages - len(hits))
        recent = self.database.get_recent_messages(limit=recent_limit, chat_ids=chat_ids, include_private=False)
        return self.database.export_context_for_codex(
            title="SQLite context for private secretary question:",
            targeted_chats=targeted,
            recent_messages=recent,
            search_hits=hits,
            max_chars=max_chars,
        )

    def for_summary(self, lookback_hours: int, max_messages: int, max_chars: int = 20000) -> str:
        if self.database is None:
            return "SQLite baza istorii ne podklyuchena."
        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        recent = self.database.get_recent_messages(
            limit=max_messages,
            since_iso=since.isoformat(timespec="seconds"),
            include_private=False,
        )
        return self.database.export_context_for_codex(
            title="SQLite context for scheduled summary:",
            targeted_chats=[],
            recent_messages=recent,
            search_hits=[],
            max_chars=max_chars,
        )

    def _targeted_chats(self, keywords: list[str], current_chat_id: int | None = None) -> list[dict]:
        targeted = []
        if current_chat_id is not None and self.database is not None:
            for chat in self.database.get_chat_list(limit=200):
                if int(chat["chat_id"]) == current_chat_id:
                    targeted.append(chat)
                    break
        if self.database is not None:
            for chat in self.database.get_chat_targets_by_keywords(keywords, limit=10):
                if not any(int(item["chat_id"]) == int(chat["chat_id"]) for item in targeted):
                    targeted.append(chat)
        return targeted

    def _keywords(self, text: str) -> list[str]:
        raw = re.findall(r"[\wА-Яа-яЁё-]{3,}", text or "", flags=re.UNICODE)
        aliases = self.config.user.aliases + [self.config.user.full_name]
        for alias in aliases:
            raw.extend(re.findall(r"[\wА-Яа-яЁё-]{3,}", alias or "", flags=re.UNICODE))
        seen = set()
        result = []
        for item in raw:
            lowered = item.lower()
            if lowered not in seen:
                seen.add(lowered)
                result.append(lowered)
        return result[:30]
