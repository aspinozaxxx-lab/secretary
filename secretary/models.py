from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TelegramUser:
    user_id: int | None
    username: str | None
    full_name: str
    is_bot: bool = False


@dataclass(slots=True)
class TelegramChat:
    chat_id: int
    chat_type: str
    title: str | None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(slots=True)
class TelegramMessage:
    update_id: int
    message_id: int
    date: int
    chat: TelegramChat
    sender: TelegramUser | None
    text: str
    raw_text: str
    has_attachments: bool
    attachment_summary: str
    is_command: bool
    command: str | None
    mentions: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    reply_to_user_id: int | None = None
    reply_to_message_id: int | None = None
    reply_to_username: str | None = None
    reply_to_text: str | None = None
    document_file_id: str | None = None
    document_file_name: str | None = None
    document_file_size: int | None = None
    document_mime_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatHistoryEntry:
    chat_id: int
    chat_title: str | None
    sender: str
    text: str
    date: int
    message_id: int


@dataclass(slots=True)
class DecisionResult:
    notify: bool
    confidence: float
    reason: str
    priority: str
    suggested_action: str
    summary: str
    source: str = "local"
    classification_error: str | None = None

    @classmethod
    def no_notify(cls, reason: str, source: str = "local") -> "DecisionResult":
        return cls(
            notify=False,
            confidence=1.0,
            reason=reason,
            priority="low",
            suggested_action="Ne trebuetsya deystviy.",
            summary="Soobschenie ne trebuet vnimaniya.",
            source=source,
        )


@dataclass(slots=True)
class CodexAnswerResult:
    answer: str | None
    error: str | None = None


@dataclass(slots=True)
class ContextRequest:
    chat_id: int | None = None
    before_message_id: int | None = None
    limit: int = 50
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BatchDecisionResult:
    items: dict[int, DecisionResult]
    batch_summary: str = ""
    need_more_context: bool = False
    context_request: ContextRequest | None = None
    raw_error: str | None = None
