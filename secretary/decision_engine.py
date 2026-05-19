from __future__ import annotations

import logging
from collections.abc import Callable

from secretary.chat_history import format_history
from secretary.codex_client import CodexClient
from secretary.config import AppConfig
from secretary.context_retriever import ContextRetriever
from secretary.models import BatchDecisionResult, ChatHistoryEntry, DecisionResult, TelegramMessage
from secretary.preferences import tone_prompt

LOGGER = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(
        self,
        config: AppConfig,
        codex_client: CodexClient,
        context_retriever: ContextRetriever | None = None,
        get_communication_tone: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.codex_client = codex_client
        self.context_retriever = context_retriever
        self.get_communication_tone = get_communication_tone

    def decide(self, message: TelegramMessage, history: list[ChatHistoryEntry]) -> DecisionResult:
        local = self.local_rules(message)
        if local is not None:
            return local

        prompt = self._build_prompt(message, history)
        result = self.codex_client.classify(prompt)
        if result.classification_error and _looks_important(message, self.config.user.aliases):
            result.notify = True
            result.confidence = max(result.confidence, self.config.decision.min_confidence_to_notify)
            result.reason = "Не удалось надежно классифицировать, но сообщение похоже на важное."
            result.summary = message.text[:500]
            result.suggested_action = "Проверь сообщение вручную."
            result.priority = "normal"
        if result.notify and result.confidence < self.config.decision.min_confidence_to_notify:
            LOGGER.info(
                "Decision suppressed by confidence: %.2f < %.2f",
                result.confidence,
                self.config.decision.min_confidence_to_notify,
            )
            result.notify = False
        return result

    def analyze_message_batch(
        self,
        messages: list[TelegramMessage],
        history: list[ChatHistoryEntry],
        additional_context: list[ChatHistoryEntry] | None = None,
        additional_context_note: str | None = None,
    ) -> BatchDecisionResult:
        if not messages:
            return BatchDecisionResult(items={})

        local_items = {
            message.message_id: local
            for message in messages
            if (local := self.local_rules(message)) is not None
        }
        prompt = self._build_batch_prompt(messages, history, additional_context, additional_context_note)
        codex_result = self.codex_client.classify_message_batch(prompt)

        items: dict[int, DecisionResult] = {}
        for message in messages:
            local = local_items.get(message.message_id)
            codex_decision = codex_result.items.get(message.message_id)
            if local is not None:
                items[message.message_id] = local
                continue
            if codex_decision is None:
                codex_decision = DecisionResult.no_notify(
                    "Codex не дал решение по сообщению.",
                    source="codex",
                )
                codex_decision.confidence = 0.0
            if codex_result.raw_error and _looks_important(message, self.config.user.aliases):
                codex_decision.notify = True
                codex_decision.confidence = max(
                    codex_decision.confidence,
                    self.config.decision.min_confidence_to_notify,
                )
                codex_decision.reason = "Не удалось надежно классифицировать, но сообщение похоже на важное."
                codex_decision.summary = message.text[:500]
                codex_decision.suggested_action = "Проверь сообщение вручную."
                codex_decision.priority = "normal"
                codex_decision.classification_error = codex_result.raw_error
            if codex_decision.notify and codex_decision.confidence < self.config.decision.min_confidence_to_notify:
                LOGGER.info(
                    "Batch decision suppressed by confidence: %.2f < %.2f",
                    codex_decision.confidence,
                    self.config.decision.min_confidence_to_notify,
                )
                codex_decision.notify = False
            items[message.message_id] = codex_decision

        codex_result.items = items
        return codex_result

    def local_rules(self, message: TelegramMessage) -> DecisionResult | None:
        usernames = set(self.config.user.telegram_usernames)
        if usernames.intersection(set(message.mentions)):
            return DecisionResult(
                notify=True,
                confidence=1.0,
                reason="Сообщение явно упоминает username пользователя.",
                priority="high",
                suggested_action="Тебя явно упомянули. Лучше открыть чат и посмотреть.",
                summary=message.text[:500],
                source="local",
            )

        reply_username = (message.reply_to_username or "").lower().lstrip("@")
        if reply_username and reply_username in usernames:
            return DecisionResult(
                notify=True,
                confidence=1.0,
                reason="Сообщение является reply на сообщение пользователя.",
                priority="high",
                suggested_action="Это ответ на твое сообщение. Лучше посмотреть.",
                summary=message.text[:500],
                source="local",
            )

        notify_user_id = self.config.telegram.notify_user_id
        if notify_user_id is not None and message.reply_to_user_id == notify_user_id:
            return DecisionResult(
                notify=True,
                confidence=1.0,
                reason="Сообщение является reply на сообщение пользователя.",
                priority="high",
                suggested_action="Это ответ на твое сообщение. Лучше посмотреть.",
                summary=message.text[:500],
                source="local",
            )

        return None

    def _build_prompt(self, message: TelegramMessage, history: list[ChatHistoryEntry]) -> str:
        aliases = ", ".join(self.config.user.aliases) or "net"
        usernames = ", ".join(f"@{item}" for item in self.config.user.telegram_usernames) or "net"
        sender = message.sender.full_name if message.sender else "unknown"
        if message.sender and message.sender.username:
            sender = f"{sender} (@{message.sender.username})"
        attachments = "est" if message.has_attachments else "net"
        tone = self._tone_prompt()
        return f"""
Ty sekretar polzovatelya. Nuzhno reshit, nado li bespokoit polzovatelya iz-za Telegram-soobscheniya.

Vozvraschay tolko JSON bez markdown i bez poyasneniy vne JSON:
{{
  "notify": true/false,
  "confidence": 0.0-1.0,
  "reason": "korotkoe obyasnenie",
  "priority": "low|normal|high|urgent",
  "suggested_action": "chto sdelat polzovatelyu",
  "summary": "korotkaya sut soobscheniya"
}}

Pravila:
- Esli soobschenie kasayetsya roley, proektov, zon otvetstvennosti ili prioritetov polzovatelya, notify=true.
- Esli soobschenie tolko fonovoe, ne trebuet ego resheniya ili ne kasayetsya ego zon otvetstvennosti, notify=false.
- Esli upomyanuty aliasy ili FIO, otseni kontekst i vazhnost.
- Ne predlagay otvechat v chat avtomaticheski.
- Pered resheniem izuchay istoriyu soobscheniy iz SQLite po vsem chatam: glavnyy aktualnyy istochnik hranitsya v {self._database_path()}.
- Nije est vyborka iz SQLite: recent/search po raznym chatam. Ne delai vyvod tolko po tekuschemu soobscheniyu, esli ego smysl zavisit ot predyduschego konteksta.
- Reason ostavlyay korotkim. Suggested_action i summary pishi prostym zhivym russkim tekstom, kotoryy mozhno pokazat polzovatelyu.

Kontekst polzovatelya:
{self.config.context_text or "Kontekst poka ne zapolnen."}

{tone}

Profil:
- full_name: {self.config.user.full_name}
- usernames: {usernames}
- aliases: {aliases}

Chat:
- chat_id: {message.chat.chat_id}
- chat_title: {message.chat.title}
- chat_type: {message.chat.chat_type}
- sender: {sender}
- message_id: {message.message_id}
- attachments: {attachments}

SQLite baza i vyborka:
{self._database_prompt_for_message(message)}

Poslednie soobscheniya chata:
{format_history(history)}

Tekuschee soobschenie:
{message.text}
""".strip()

    def _build_batch_prompt(
        self,
        messages: list[TelegramMessage],
        history: list[ChatHistoryEntry],
        additional_context: list[ChatHistoryEntry] | None,
        additional_context_note: str | None,
    ) -> str:
        aliases = ", ".join(self.config.user.aliases) or "net"
        usernames = ", ".join(f"@{item}" for item in self.config.user.telegram_usernames) or "net"
        first = messages[0]
        message_lines = "\n".join(_format_batch_message(message) for message in messages)
        tone = self._tone_prompt()
        additional = "Dopolnitelnyy kontekst ne zaprashivalsya."
        if additional_context is not None:
            additional = format_history(additional_context)
            if additional_context_note:
                additional = f"{additional_context_note}\n{additional}"
        return f"""
Ty sekretar polzovatelya. Nuzhno otsenit pachku Telegram-soobscheniy i reshit po kazhdomu message_id, nado li bespokoit polzovatelya.

Vozvraschay tolko JSON bez markdown i bez poyasneniy vne JSON:
{{
  "items": [
    {{
      "message_id": 123,
      "notify": true/false,
      "confidence": 0.0-1.0,
      "reason": "korotkaya prichina",
      "priority": "low|normal|high|urgent",
      "suggested_action": "chto sdelat polzovatelyu",
      "summary": "korotkaya sut"
    }}
  ],
  "batch_summary": "kratkaya svodka pachki",
  "need_more_context": false,
  "context_request": null
}}

Esli ne hvataet lokalnogo konteksta, mozhno odin raz zaprosit dopolnitelnyy kontekst:
{{
  "need_more_context": true,
  "context_request": {{
    "chat_id": {first.chat.chat_id},
    "before_message_id": {first.message_id},
    "limit": 50,
    "keywords": ["klyuchevoe slovo"]
  }}
}}

Pravila:
- V items dolzhen byt element dlya kazhdogo message_id iz pachki.
- Esli soobschenie kasayetsya roley, proektov, zon otvetstvennosti ili prioritetov polzovatelya, notify=true.
- Esli soobschenie tolko fonovoe, ne trebuet ego resheniya ili ne kasayetsya ego zon otvetstvennosti, notify=false.
- Ne vydumyvay fakty, kotoryh net v istorii ili context.md.
- Ne predlagay otvechat v chat avtomaticheski.
- Pered resheniyami izuchay istoriyu soobscheniy iz SQLite po vsem chatam: glavnyy aktualnyy istochnik hranitsya v {self._database_path()}.
- Nije est vyborka iz SQLite: recent/search po raznym chatam. Ne delai vyvod tolko po otdelnomu soobscheniyu, esli ego smysl zavisit ot predyduschego konteksta.
- Reason ostavlyay korotkim. Suggested_action, summary i batch_summary pishi prostym zhivym russkim tekstom, kotoryy mozhno pokazat polzovatelyu.

Kontekst polzovatelya:
{self.config.context_text or "Kontekst poka ne zapolnen."}

{tone}

Profil:
- full_name: {self.config.user.full_name}
- usernames: {usernames}
- aliases: {aliases}

Chat:
- chat_id: {first.chat.chat_id}
- chat_title: {first.chat.title}
- chat_type: {first.chat.chat_type}

SQLite baza i vyborka:
{self._database_prompt_for_batch(messages)}

Istoriya chata do pachki:
{format_history(history)}

Dopolnitelnyy kontekst:
{additional}

Pachka soobscheniy:
{message_lines}
""".strip()

    def _database_prompt_for_message(self, message: TelegramMessage) -> str:
        if self.context_retriever is None:
            return "SQLite baza istorii ne podklyuchena."
        return self.context_retriever.for_message(message)

    def _database_prompt_for_batch(self, messages: list[TelegramMessage]) -> str:
        if self.context_retriever is None:
            return "SQLite baza istorii ne podklyuchena."
        return self.context_retriever.for_batch(messages)

    def _tone_prompt(self) -> str:
        if self.get_communication_tone is None:
            return tone_prompt(self.config.secretary.communication_tone)
        return tone_prompt(self.get_communication_tone())

    def _database_path(self) -> str:
        path = self.config.database.path or (self.config.root_dir / "chat_history.sqlite3")
        return str(path)


def _format_batch_message(message: TelegramMessage) -> str:
    sender = message.sender.full_name if message.sender else "unknown"
    if message.sender and message.sender.username:
        sender = f"{sender} (@{message.sender.username})"
    reply = ""
    if message.reply_to_user_id or message.reply_to_username or message.reply_to_text:
        reply = (
            f"; reply_to_user_id={message.reply_to_user_id}; "
            f"reply_to_username={message.reply_to_username}; reply_text={message.reply_to_text or ''}"
        )
    mentions = ", ".join(f"@{item}" for item in message.mentions) or "net"
    text = (message.text or "[net teksta]").replace("\r", " ").replace("\n", " ").strip()
    return (
        f"- message_id={message.message_id}; update_id={message.update_id}; date={message.date}; "
        f"sender={sender}; mentions={mentions}{reply}; text={text}"
    )


def _looks_important(message: TelegramMessage, aliases: list[str]) -> bool:
    text = message.text.lower()
    important_words = ("срочно", "важно", "нужно", "проблем", "авар", "urgent", "asap")
    if any(word in text for word in important_words):
        return True
    return any(alias.lower() in text for alias in aliases if alias)
