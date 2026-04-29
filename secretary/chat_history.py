from __future__ import annotations

from datetime import datetime

from secretary.models import ChatHistoryEntry


def format_history(entries: list[ChatHistoryEntry]) -> str:
    lines: list[str] = []
    for entry in entries:
        ts = _format_ts(entry.date)
        text = entry.text.replace("\r", " ").replace("\n", " ").strip()
        lines.append(f"- [{ts}] {entry.sender}: {text}")
    return "\n".join(lines) if lines else "Istoriya chata poka pusta."


def _format_ts(value: int) -> str:
    if not value:
        return "unknown"
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")
