from __future__ import annotations

import logging
import sys
from pathlib import Path

from secretary.archive import ChatArchive
from secretary.codex_client import CodexClient
from secretary.config import AppConfig, load_config
from secretary.decision_engine import DecisionEngine
from secretary.events import EventBus, emit_if_present
from secretary.logging_setup import setup_logging
from secretary.models import DecisionResult, TelegramMessage
from secretary.notifier import Notifier
from secretary.polling import PollingLoop
from secretary.secretary_assistant import SecretaryAssistant
from secretary.summary import SummaryService
from secretary.state import StateStore
from secretary.telegram_client import TelegramClient

LOGGER = logging.getLogger(__name__)

TELEGRAM_COMMANDS = [
    {"command": "ping", "description": "Проверить связь с ботом"},
    {"command": "status", "description": "Показать состояние бота"},
    {"command": "chats", "description": "Показать известные чаты"},
    {"command": "whoami", "description": "Показать мой user_id и chat_id"},
    {"command": "summary", "description": "Сделать саммари по чатам сейчас"},
    {"command": "testnotify", "description": "Проверить отправку уведомлений"},
    {"command": "testdecision", "description": "Проверить путь decision → notification"},
    {"command": "reload", "description": "Перечитать config.yaml и context.md"},
    {"command": "help", "description": "Показать справку"},
]


class SecretaryApp:
    def __init__(self, config_path: Path, event_bus: EventBus | None = None) -> None:
        self.config_path = config_path.resolve()
        self.event_bus = event_bus
        self.config = self._load_and_apply_config()
        self.commands_menu_status = "not registered"
        self.state = StateStore(
            self.config.storage.state_file,
            self.config.storage.history_limit_per_chat,
        )
        self.state.load()
        self.archive = ChatArchive(self.config)
        self.loop = self._build_loop()

    def run(self) -> None:
        self._startup_check()
        self.loop.run_forever()

    def stop(self) -> None:
        self.loop.stop()
        self.state.save()
        emit_if_present(self.event_bus, "system", "Bot stop requested", direction="system")

    def reload(self) -> None:
        LOGGER.info("Reloading config and context")
        self.config = self._load_and_apply_config()
        self.state.path = self.config.storage.state_file
        self.state.history_limit_per_chat = self.config.storage.history_limit_per_chat
        self.archive = ChatArchive(self.config)
        self._apply_runtime_components(self.loop)

    def _load_and_apply_config(self) -> AppConfig:
        config = load_config(self.config_path)
        setup_logging(config.logging.level, config.logging.file, [config.telegram.bot_token])
        return config

    def _build_loop(self) -> PollingLoop:
        client, codex_client, decision_engine, notifier, assistant = self._create_runtime_components()
        return PollingLoop(
            client=client,
            state=self.state,
            decision_engine=decision_engine,
            notifier=notifier,
            is_allowed_message=self._is_allowed_message,
            handle_command=self._handle_command,
            handle_private_text=self._handle_private_text,
            check_scheduled_tasks=self._check_scheduled_tasks,
            event_bus=self.event_bus,
            archive=self.archive,
        )

    def _apply_runtime_components(self, loop: PollingLoop) -> None:
        client, codex_client, decision_engine, notifier, assistant = self._create_runtime_components()
        loop.client = client
        loop.decision_engine = decision_engine
        loop.notifier = notifier
        loop.archive = self.archive
        self.assistant = assistant
        self.summary_service = SummaryService(self.config, self.state, client, codex_client, self.archive, self.event_bus)

    def _create_runtime_components(
        self,
    ) -> tuple[TelegramClient, CodexClient, DecisionEngine, Notifier, SecretaryAssistant]:
        client = TelegramClient(self.config.telegram.bot_token, event_bus=self.event_bus)
        codex_client = CodexClient(
            self.config.codex.command,
            self.config.codex.timeout_seconds,
            self.config.root_dir,
            self.config.codex.prompt_max_chars,
            event_bus=self.event_bus,
        )
        decision_engine = DecisionEngine(self.config, codex_client, self.archive)
        notifier = Notifier(client, self.config.telegram, self.event_bus)
        assistant = SecretaryAssistant(self.config, self.state, codex_client, self.archive)
        self.assistant = assistant
        self.summary_service = SummaryService(self.config, self.state, client, codex_client, self.archive, self.event_bus)
        return client, codex_client, decision_engine, notifier, assistant

    def _check_scheduled_tasks(self) -> None:
        if hasattr(self, "summary_service"):
            self.summary_service.send_due_summaries()

    def _startup_check(self) -> None:
        LOGGER.info("Python version: %s", sys.version.split()[0])
        LOGGER.info("Project root: %s", self.config.root_dir)
        LOGGER.info("Config loaded: %s", self.config.path)
        LOGGER.info("Archive dir: %s", self.config.archive.dir)
        codex_client = self.loop.decision_engine.codex_client
        LOGGER.info("Codex command resolved: %s", "yes" if codex_client.resolve_command() else "no")
        emit_if_present(
            self.event_bus,
            "system",
            f"Бот запускается. Проект: {self.config.root_dir}",
            direction="system",
        )
        try:
            webhook_info = self.loop.client.get_webhook_info()
            webhook_set = bool(webhook_info.get("url"))
            LOGGER.info(
                "Telegram webhook status: %s, pending updates: %s",
                "set" if webhook_set else "not set",
                webhook_info.get("pending_update_count"),
            )
            if webhook_set:
                self.loop.client.delete_webhook()
                LOGGER.warning("Telegram webhook was set and has been deleted")
                emit_if_present(self.event_bus, "system", "Telegram webhook был удален", direction="system")
        except Exception as exc:
            LOGGER.warning("Telegram webhook status check failed: %s", exc)
            emit_if_present(self.event_bus, "error", f"Telegram webhook status check failed: {exc}", direction="error")
        self.register_telegram_commands()

    def register_telegram_commands(self) -> bool:
        try:
            self.loop.client.set_my_commands(TELEGRAM_COMMANDS)
            registered = self.loop.client.get_my_commands()
        except Exception as exc:
            self.commands_menu_status = f"error: {exc}"
            LOGGER.warning("Telegram commands menu registration failed: %s", exc)
            emit_if_present(
                self.event_bus,
                "error",
                f"Не удалось обновить меню команд Telegram: {exc}",
                direction="error",
            )
            return False
        names = ", ".join(f"/{item.get('command')}" for item in registered)
        self.commands_menu_status = f"registered yes ({len(registered)})"
        LOGGER.info("Telegram commands menu registered: %s", names)
        emit_if_present(
            self.event_bus,
            "system",
            "Меню команд Telegram обновлено",
            direction="system",
        )
        return True

    def _is_allowed_message(self, message: TelegramMessage) -> bool:
        allowed = self.config.telegram.allowed_chat_ids
        if not allowed or message.chat.chat_id in allowed:
            return True
        return message.chat.chat_type == "private" and self._is_owner(message)

    def _is_owner(self, message: TelegramMessage) -> bool:
        if not message.sender:
            return False
        configured_user_id = self.config.user.telegram_user_id
        if configured_user_id is not None:
            return message.sender.user_id == configured_user_id
        username = _sender_username(message)
        return bool(username and username in self.config.user.telegram_usernames)

    def _handle_command(self, message: TelegramMessage) -> bool:
        command = message.command
        if command not in {
            "/ping",
            "/status",
            "/help",
            "/reload",
            "/whoami",
            "/chats",
            "/testnotify",
            "/testdecision",
            "/summary",
            "/setcommands",
        }:
            return False

        client = self.loop.client
        owner_only = {"/testnotify", "/testdecision", "/summary", "/setcommands"}
        if command in owner_only and not self._is_owner(message):
            client.send_message(message.chat.chat_id, "Нет доступа.", reply_to_message_id=message.message_id)
            return True
        if command == "/ping":
            client.send_message(message.chat.chat_id, "pong", reply_to_message_id=message.message_id)
        elif command == "/status":
            client.send_message(
                message.chat.chat_id,
                self._status_text(),
                reply_to_message_id=message.message_id,
            )
        elif command == "/help":
            client.send_message(
                message.chat.chat_id,
                _help_text(),
                reply_to_message_id=message.message_id,
            )
        elif command == "/reload":
            self.reload()
            self.loop.client.send_message(
                message.chat.chat_id,
                "Конфигурация и контекст перечитаны.",
                reply_to_message_id=message.message_id,
            )
        elif command == "/whoami":
            client.send_message(
                message.chat.chat_id,
                _whoami_text(message),
                reply_to_message_id=message.message_id,
            )
        elif command == "/chats":
            client.send_message(
                message.chat.chat_id,
                self._chats_text(),
                reply_to_message_id=message.message_id,
            )
        elif command == "/testnotify":
            ok, text = self.loop.notifier.send_test_notification("Тестовое уведомление от Telegram Secretary Bot.")
            client.send_message(message.chat.chat_id, text, reply_to_message_id=message.message_id)
        elif command == "/testdecision":
            decision = DecisionResult(
                notify=True,
                confidence=1.0,
                reason="Ручная проверка связки decision -> notifier.",
                priority="normal",
                suggested_action="Проверить, что уведомление пришло.",
                summary="Тестовое decision-событие.",
                source="test",
            )
            self.loop.notifier.notify(message, decision)
            client.send_message(
                message.chat.chat_id,
                "Тестовое decision-событие отправлено в notifier.",
                reply_to_message_id=message.message_id,
            )
        elif command == "/summary":
            ok = self.summary_service.send_summary(schedule_time="manual")
            client.send_message(
                message.chat.chat_id,
                "Summary отправлено." if ok else "Summary не отправлено, смотри лог.",
                reply_to_message_id=message.message_id,
            )
        elif command == "/setcommands":
            ok = self.register_telegram_commands()
            client.send_message(
                message.chat.chat_id,
                "Меню команд Telegram обновлено." if ok else "Не удалось обновить меню команд Telegram.",
                reply_to_message_id=message.message_id,
            )
        return True

    def _handle_private_text(self, message: TelegramMessage) -> bool:
        if message.chat.chat_type != "private" or message.is_command or not message.text:
            return False
        if not self._is_owner(message):
            self.loop.client.send_message(message.chat.chat_id, "Нет доступа.", reply_to_message_id=message.message_id)
            return True
        if not self.config.secretary.enable_private_assistant:
            self.loop.client.send_message(
                message.chat.chat_id,
                "Режим личного секретаря отключен.",
                reply_to_message_id=message.message_id,
            )
            return True
        result = self.assistant.answer(message)
        if result.error:
            self.loop.client.send_message(
                message.chat.chat_id,
                f"Не смог надежно подготовить ответ: {result.error}",
                reply_to_message_id=message.message_id,
            )
            return True
        self.loop.client.send_message(
            message.chat.chat_id,
            result.answer or "В доступной истории этого не видно.",
            reply_to_message_id=message.message_id,
        )
        return True

    def _status_text(self) -> str:
        offset = self.state.next_offset
        access_mode = "все чаты" if not self.config.telegram.allowed_chat_ids else "только allowed_chat_ids"
        return (
            "Бот работает.\n"
            f"Offset: {offset if offset is not None else 'нет'}\n"
            f"Известных чатов: {self.state.known_chats_count()}\n"
            f"Режим доступа: {access_mode}\n"
            f"Личный секретарь: {'включен' if self.config.secretary.enable_private_assistant else 'выключен'}\n"
            f"Owner user_id задан: {'да' if self.config.user.telegram_user_id is not None else 'нет'}\n"
            f"Summary: {'включено' if self.config.summary.enabled else 'выключено'} "
            f"({', '.join(self.config.summary.times or [])})\n"
            f"Telegram commands menu: {self.commands_menu_status}\n"
            f"Конфиг: {self.config.path}"
        )

    def _chats_text(self) -> str:
        chats = self.state.list_chats(limit=30)
        if not chats:
            return "Известных чатов пока нет."
        lines = ["Известные чаты:"]
        for chat in chats:
            name = _chat_name(chat)
            lines.append(
                f"{chat.get('chat_id')} | {chat.get('type') or 'unknown'} | {name} | {chat.get('last_seen_at') or 'нет'}"
            )
        if self.state.known_chats_count() > len(chats):
            lines.append(f"Показаны последние {len(chats)} из {self.state.known_chats_count()}.")
        return "\n".join(lines)


def _help_text() -> str:
    return (
        "Команды:\n"
        "/ping — проверка связи\n"
        "/status — состояние бота\n"
        "/chats — список известных чатов\n"
        "/testnotify — проверить отправку уведомлений\n"
        "/testdecision — проверить путь decision -> notifier\n"
        "/summary — отправить summary вручную\n"
        "/setcommands — обновить меню команд Telegram\n"
        "/reload — перечитать конфигурацию и контекст\n"
        "/whoami — показать chat_id и user_id\n"
        "/help — справка"
    )


def _whoami_text(message: TelegramMessage) -> str:
    user_id = message.sender.user_id if message.sender else "нет"
    username = message.sender.username if message.sender and message.sender.username else "нет"
    return (
        f"chat_id: {message.chat.chat_id}\n"
        f"chat_type: {message.chat.chat_type}\n"
        f"user_id: {user_id}\n"
        f"username: {username}"
    )


def _sender_username(message: TelegramMessage) -> str:
    if not message.sender or not message.sender.username:
        return ""
    return message.sender.username.lower().lstrip("@")


def _chat_name(chat: dict) -> str:
    title = chat.get("title") or chat.get("chat_title")
    if title:
        return str(title)
    first_name = str(chat.get("first_name") or "").strip()
    last_name = str(chat.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    return full_name or str(chat.get("username") or "без названия")
