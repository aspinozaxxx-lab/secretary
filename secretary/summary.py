from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from secretary.archive import ChatArchive
from secretary.chat_history import format_history
from secretary.codex_client import CodexClient
from secretary.config import AppConfig
from secretary.events import EventBus, emit_if_present
from secretary.state import StateStore
from secretary.telegram_client import TelegramClient

LOGGER = logging.getLogger(__name__)


class SummaryService:
    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        client: TelegramClient,
        codex_client: CodexClient,
        archive: ChatArchive,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.client = client
        self.codex_client = codex_client
        self.archive = archive
        self.event_bus = event_bus
        self._last_check_monotonic = 0.0

    def send_due_summaries(self) -> None:
        if not self.config.summary.enabled:
            return
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_check_monotonic < 30:
            return
        self._last_check_monotonic = now_monotonic
        now = datetime.now(ZoneInfo(self.config.summary.timezone))
        date_key = now.date().isoformat()
        for schedule_time in self.config.summary.times or []:
            scheduled = _scheduled_datetime(now, schedule_time)
            if now < scheduled:
                continue
            if now - scheduled > timedelta(minutes=2):
                continue
            if self.state.get_last_summary_sent(schedule_time) == date_key:
                continue
            if self.send_summary(schedule_time=schedule_time):
                self.state.mark_summary_sent(schedule_time, date_key)
                self.state.save()

    def send_summary(self, schedule_time: str = "manual") -> bool:
        target_chat_id = (
            self.config.summary.target_chat_id
            or self.config.telegram.notify_chat_id
            or self.config.telegram.notify_user_id
        )
        if target_chat_id is None:
            LOGGER.error("Summary target is not configured")
            emit_if_present(self.event_bus, "error", "Некуда отправлять summary: target_chat_id не задан", direction="error")
            return False

        now = datetime.now(ZoneInfo(self.config.summary.timezone))
        since = now - timedelta(hours=self.config.summary.lookback_hours)
        messages = self.state.get_recent_messages_since(
            int(since.timestamp()),
            limit=self.config.summary.max_messages,
            include_private=False,
        )
        prompt = self._build_prompt(messages, now, schedule_time)
        result = self.codex_client.answer_secretary_question(prompt)
        if result.error:
            text = f"Не смог подготовить summary: {result.error}"
            emit_if_present(self.event_bus, "error", text, direction="error")
        else:
            text = result.answer or "В доступной истории за период нет заметных событий."
        try:
            self.client.send_message(target_chat_id, text)
        except Exception as exc:
            LOGGER.exception("Summary send failed")
            emit_if_present(self.event_bus, "error", f"Summary не отправлено: {exc}", direction="error")
            return False
        emit_if_present(self.event_bus, "system", f"Summary отправлено ({schedule_time})", direction="system")
        return True

    def _build_prompt(self, messages: list, now: datetime, schedule_time: str) -> str:
        return f"""
Ty lokalnyy Telegram-sekretar polzovatelya. Sdelay kratkoe mini-summary po rabochim chatam na russkom.

Kontekst polzovatelya:
{self.config.context_text or "Kontekst poka ne zapolnen."}

Parametry:
- schedule_time: {schedule_time}
- timezone: {self.config.summary.timezone}
- now: {now.isoformat(timespec="seconds")}
- lookback_hours: {self.config.summary.lookback_hours}
- include_low_priority: {self.config.summary.include_low_priority}

Lokalnyy arhiv:
{self.archive.describe_for_prompt()}

Soobscheniya za period:
{format_history(messages)}

Instruktsii:
- Verni obychnyy tekst, ne JSON.
- Ne vydumyvay.
- Gruppiruy po chatam/proektam, esli eto umestno.
- Esli vazhnogo net ili dannyh malo, skazhi eto pryamo.
- Ne raskryvay bot token/config secrets.
""".strip()


def _scheduled_datetime(now: datetime, schedule_time: str) -> datetime:
    hour_text, minute_text = schedule_time.split(":", maxsplit=1)
    return now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
