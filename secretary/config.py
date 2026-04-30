from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class TelegramConfig:
    bot_token: str
    notify_chat_id: int | None
    notify_user_id: int | None
    allowed_chat_ids: list[int]
    bot_username: str


@dataclass(slots=True)
class UserConfig:
    telegram_user_id: int | None
    telegram_usernames: list[str]
    full_name: str
    aliases: list[str]
    context_file: Path


@dataclass(slots=True)
class CodexConfig:
    command: str
    timeout_seconds: int
    prompt_max_chars: int = 24000


@dataclass(slots=True)
class DecisionConfig:
    min_confidence_to_notify: float
    batch_enabled: bool = True
    batch_max_messages: int = 30
    batch_max_chars: int = 12000
    batch_max_age_seconds: int = 90
    batch_flush_interval_seconds: int = 5


@dataclass(slots=True)
class StorageConfig:
    state_file: Path
    history_limit_per_chat: int = 500
    history_max_messages_per_chat: int = 500


@dataclass(slots=True)
class LoggingConfig:
    level: str
    file: Path


@dataclass(slots=True)
class SecretaryConfig:
    enable_private_assistant: bool = True
    max_context_messages: int = 80
    max_answer_chars: int = 3500


@dataclass(slots=True)
class ArchiveConfig:
    enabled: bool = True
    dir: Path | None = None
    format: str = "jsonl"
    also_write_markdown: bool = True


@dataclass(slots=True)
class SummaryConfig:
    enabled: bool = True
    times: list[str] | None = None
    timezone: str = "Europe/Moscow"
    lookback_hours: int = 6
    max_messages: int = 200
    target_chat_id: int | None = None
    include_low_priority: bool = True


@dataclass(slots=True)
class AppConfig:
    telegram: TelegramConfig
    user: UserConfig
    codex: CodexConfig
    decision: DecisionConfig
    storage: StorageConfig
    logging: LoggingConfig
    secretary: SecretaryConfig
    archive: ArchiveConfig
    summary: SummaryConfig
    path: Path
    root_dir: Path
    context_text: str = ""


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.example.yaml to config.yaml and fill it."
        )

    with config_path.open("r", encoding="utf-8-sig") as stream:
        raw = yaml.safe_load(stream) or {}

    root_dir = config_path.parent.resolve()

    telegram_raw = _section(raw, "telegram")
    user_raw = _section(raw, "user")
    codex_raw = _section(raw, "codex")
    decision_raw = _section(raw, "decision")
    storage_raw = _section(raw, "storage")
    logging_raw = _section(raw, "logging")
    secretary_raw = raw.get("secretary") or {}
    if not isinstance(secretary_raw, dict):
        raise ValueError("Missing or invalid section: secretary")
    archive_raw = raw.get("archive") or {}
    if not isinstance(archive_raw, dict):
        raise ValueError("Missing or invalid section: archive")
    summary_raw = raw.get("summary") or {}
    if not isinstance(summary_raw, dict):
        raise ValueError("Missing or invalid section: summary")

    telegram = TelegramConfig(
        bot_token=_required_str(telegram_raw, "bot_token"),
        notify_chat_id=_optional_int(telegram_raw.get("notify_chat_id")),
        notify_user_id=_optional_int(telegram_raw.get("notify_user_id")),
        allowed_chat_ids=_int_list(telegram_raw.get("allowed_chat_ids", [])),
        bot_username=_required_str(telegram_raw, "bot_username").lstrip("@"),
    )
    user = UserConfig(
        telegram_user_id=_optional_int(user_raw.get("telegram_user_id")),
        telegram_usernames=[item.lstrip("@").lower() for item in _str_list(user_raw.get("telegram_usernames", []))],
        full_name=str(user_raw.get("full_name", "")).strip(),
        aliases=[item.strip() for item in _str_list(user_raw.get("aliases", [])) if item.strip()],
        context_file=_resolve_path(root_dir, user_raw.get("context_file", "context.md")),
    )
    codex = CodexConfig(
        command=str(codex_raw.get("command", "codex")).strip() or "codex",
        timeout_seconds=int(codex_raw.get("timeout_seconds", 120)),
        prompt_max_chars=int(codex_raw.get("prompt_max_chars", 24000)),
    )
    decision = DecisionConfig(
        min_confidence_to_notify=float(decision_raw.get("min_confidence_to_notify", 0.7)),
        batch_enabled=bool(decision_raw.get("batch_enabled", True)),
        batch_max_messages=int(decision_raw.get("batch_max_messages", 30)),
        batch_max_chars=int(decision_raw.get("batch_max_chars", 12000)),
        batch_max_age_seconds=int(decision_raw.get("batch_max_age_seconds", 90)),
        batch_flush_interval_seconds=int(decision_raw.get("batch_flush_interval_seconds", 5)),
    )
    history_max_messages = int(
        storage_raw.get(
            "history_max_messages_per_chat",
            max(int(storage_raw.get("history_limit_per_chat", 500)), 500),
        )
    )
    storage = StorageConfig(
        state_file=_resolve_path(root_dir, storage_raw.get("state_file", "state.json")),
        history_limit_per_chat=history_max_messages,
        history_max_messages_per_chat=history_max_messages,
    )
    logging_config = LoggingConfig(
        level=str(logging_raw.get("level", "INFO")).upper(),
        file=_resolve_path(root_dir, logging_raw.get("file", "logs/secretary.log")),
    )
    secretary = SecretaryConfig(
        enable_private_assistant=bool(secretary_raw.get("enable_private_assistant", True)),
        max_context_messages=int(secretary_raw.get("max_context_messages", 80)),
        max_answer_chars=int(secretary_raw.get("max_answer_chars", 3500)),
    )
    archive_dir_value = archive_raw.get("dir", "chat_archive")
    if archive_dir_value in (None, ""):
        archive_dir_value = "chat_archive"
    archive = ArchiveConfig(
        enabled=bool(archive_raw.get("enabled", True)),
        dir=_resolve_path(root_dir, archive_dir_value),
        format=str(archive_raw.get("format", "jsonl")).strip().lower() or "jsonl",
        also_write_markdown=bool(archive_raw.get("also_write_markdown", True)),
    )
    summary = SummaryConfig(
        enabled=bool(summary_raw.get("enabled", True)),
        times=_str_list(summary_raw.get("times", ["13:00", "18:00"])),
        timezone=str(summary_raw.get("timezone", "Europe/Moscow")).strip() or "Europe/Moscow",
        lookback_hours=int(summary_raw.get("lookback_hours", 6)),
        max_messages=int(summary_raw.get("max_messages", 200)),
        target_chat_id=_optional_int(summary_raw.get("target_chat_id")),
        include_low_priority=bool(summary_raw.get("include_low_priority", True)),
    )

    context_text = ""
    if user.context_file.exists():
        context_text = user.context_file.read_text(encoding="utf-8-sig")

    return AppConfig(
        telegram=telegram,
        user=user,
        codex=codex,
        decision=decision,
        storage=storage,
        logging=logging_config,
        secretary=secretary,
        archive=archive,
        summary=summary,
        path=config_path,
        root_dir=root_dir,
        context_text=context_text,
    )


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid section: {name}")
    return value


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value or value.startswith("PUT_"):
        raise ValueError(f"Missing required config value: {key}")
    return value


def _optional_int(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected list of integers")
    return [int(item) for item in value if str(item).strip()]


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected list of strings")
    return [str(item) for item in value]


def _resolve_path(root_dir: Path, value: Any) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = root_dir / path
    return path.resolve()
