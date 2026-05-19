from __future__ import annotations

from collections.abc import Callable

from secretary.chat_history import format_history
from secretary.codex_client import CodexClient
from secretary.config import AppConfig
from secretary.context_retriever import ContextRetriever
from secretary.models import CodexAnswerResult, TelegramMessage
from secretary.preferences import tone_prompt
from secretary.state import StateStore


class SecretaryAssistant:
    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        codex_client: CodexClient,
        context_retriever: ContextRetriever | None = None,
        get_communication_tone: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.codex_client = codex_client
        self.context_retriever = context_retriever
        self.get_communication_tone = get_communication_tone

    def answer(self, message: TelegramMessage) -> CodexAnswerResult:
        history = self.state.get_recent_messages(
            limit=self.config.secretary.max_context_messages,
            question=message.text,
            include_private=False,
        )
        database_context = self._database_prompt(message.text)
        prompt = self._build_prompt(message.text, format_history(list(reversed(history))), database_context)
        result = self.codex_client.answer_secretary_question(prompt)
        if result.answer:
            result.answer = _trim_answer(result.answer, self.config.secretary.max_answer_chars)
        return result

    def _build_prompt(self, question: str, history_text: str, database_context: str) -> str:
        return f"""
Ty lokalnyy Telegram-sekretar polzovatelya. Otvechay kratko i po delu na russkom.

Kontekst polzovatelya:
{self.config.context_text or "Kontekst poka ne zapolnen."}

{self._tone_prompt()}

Vopros polzovatelya:
{question}

SQLite baza i vyborka:
{database_context}

Poslednie soobscheniya iz izvestnyh rabochih chatov:
{history_text}

Instruktsii:
- Ne vydumyvay fakty.
- Esli dannyh v dostupnoy istorii nedostatochno, pryamo skazhi, chto v dostupnoy istorii etogo ne vidno.
- Glavnyy aktualnyy istochnik istorii - SQLite baza {self._database_path()}; uchityvay istoriyu po vsem rabochim chatam, a ne tolko poslednie soobscheniya.
- Mozhno ssylatsya na nazvanie chata, avtora, vremya i tekst soobscheniya.
- Verni obychnyy tekst otveta, ne JSON i ne markdown-tablitsu.
- Ne pishi slishkom dlinno.
- Ne raskryvay bot token, config secrets i drugie sekrety.
- Ne predlagay deystviya, kotorye bot ne umeet vypolnyat.
""".strip()

    def _database_prompt(self, question: str) -> str:
        if self.context_retriever is None:
            return "SQLite baza istorii ne podklyuchena."
        return self.context_retriever.for_question(question, self.config.secretary.max_context_messages)

    def _tone_prompt(self) -> str:
        if self.get_communication_tone is None:
            return tone_prompt(self.config.secretary.communication_tone)
        return tone_prompt(self.get_communication_tone())

    def _database_path(self) -> str:
        path = self.config.database.path or (self.config.root_dir / "chat_history.sqlite3")
        return str(path)


def _trim_answer(answer: str, max_chars: int) -> str:
    if len(answer) <= max_chars:
        return answer
    suffix = "\n\nОтвет сокращен из-за ограничения длины."
    return answer[: max(0, max_chars - len(suffix))].rstrip() + suffix
