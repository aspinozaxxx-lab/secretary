from __future__ import annotations

DEFAULT_COMMUNICATION_TONE = "простой, понятный, разговорный, без официоза"
MAX_COMMUNICATION_TONE_CHARS = 160


def normalize_communication_tone(value: str | None) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return DEFAULT_COMMUNICATION_TONE
    return text[:MAX_COMMUNICATION_TONE_CHARS].strip() or DEFAULT_COMMUNICATION_TONE


def tone_prompt(tone: str | None) -> str:
    normalized = normalize_communication_tone(tone)
    return (
        f"Тон общения: {normalized}. "
        "Пиши в этом стиле во всех текстах для пользователя: коротко, понятно, живым языком, "
        "без канцелярита и лишней формы, если сам тон явно не просит обратного."
    )
