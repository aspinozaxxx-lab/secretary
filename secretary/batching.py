from __future__ import annotations

from secretary.models import TelegramMessage


def split_message_batches(
    messages: list[TelegramMessage],
    max_messages: int,
    max_chars: int,
    max_age_seconds: int,
) -> list[list[TelegramMessage]]:
    if not messages:
        return []
    max_messages = max(1, max_messages)
    max_chars = max(500, max_chars)
    max_age_seconds = max(1, max_age_seconds)

    ordered = sorted(messages, key=lambda item: (item.chat.chat_id, item.date, item.update_id, item.message_id))
    batches: list[list[TelegramMessage]] = []
    current: list[TelegramMessage] = []
    current_chars = 0
    first_date = 0
    current_chat_id: int | None = None

    for message in ordered:
        size = _message_size(message)
        should_flush = False
        if current:
            should_flush = (
                message.chat.chat_id != current_chat_id
                or len(current) >= max_messages
                or current_chars + size > max_chars
                or abs(message.date - first_date) > max_age_seconds
            )
        if should_flush:
            batches.append(current)
            current = []
            current_chars = 0
            first_date = 0
            current_chat_id = None

        if not current:
            first_date = message.date
            current_chat_id = message.chat.chat_id
        current.append(message)
        current_chars += size

    if current:
        batches.append(current)
    return batches


def _message_size(message: TelegramMessage) -> int:
    sender = message.sender.full_name if message.sender else "unknown"
    return len(message.text or "") + len(sender) + 80
