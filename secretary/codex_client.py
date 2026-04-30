from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from secretary.events import EventBus, emit_if_present
from secretary.models import BatchDecisionResult, CodexAnswerResult, ContextRequest, DecisionResult

LOGGER = logging.getLogger(__name__)


class CodexClient:
    def __init__(
        self,
        command: str,
        timeout_seconds: int,
        root_dir: Path,
        prompt_max_chars: int,
        event_bus: EventBus | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.root_dir = root_dir
        self.prompt_max_chars = prompt_max_chars
        self.event_bus = event_bus

    def resolve_command(self) -> str | None:
        return _resolve_command_executable(self.command)

    def classify(self, prompt: str) -> DecisionResult:
        prompt = _limit_prompt(prompt, self.prompt_max_chars)
        raw, error = self._run_codex(prompt, "classification")
        if error:
            return _fallback_result(error)
        LOGGER.debug("Codex stdout tail: %s", raw[-4000:])
        try:
            data = _extract_json(raw)
            return _decision_from_json(data)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.error("Codex JSON parse failed: %s", exc)
            emit_if_present(self.event_bus, "error", f"Codex JSON parse failed: {exc}", direction="error")
            return _fallback_result(f"Codex JSON parse failed: {exc}")

    def classify_message_batch(self, prompt: str) -> BatchDecisionResult:
        prompt = _limit_prompt(prompt, self.prompt_max_chars)
        raw, error = self._run_codex(prompt, "batch classification")
        if error:
            return BatchDecisionResult(items={}, raw_error=error)
        LOGGER.debug("Codex batch stdout tail: %s", raw[-4000:])
        try:
            data = _extract_json(raw)
            return _batch_decision_from_json(data)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            message = f"Codex batch JSON parse failed: {exc}"
            LOGGER.error("%s", message)
            emit_if_present(self.event_bus, "error", message, direction="error")
            return BatchDecisionResult(items={}, raw_error=message)

    def answer_secretary_question(self, prompt: str) -> CodexAnswerResult:
        prompt = _limit_prompt(prompt, self.prompt_max_chars)
        answer, error = self._run_codex(prompt, "secretary answer")
        if error:
            return CodexAnswerResult(answer=None, error=error)
        answer = answer.strip()
        if not answer:
            emit_if_present(self.event_bus, "error", "Codex returned empty answer", direction="error")
            return CodexAnswerResult(answer=None, error="empty Codex answer")
        return CodexAnswerResult(answer=answer)

    def _run_codex(self, prompt: str, label: str) -> tuple[str, str | None]:
        try:
            args = self._build_args()
        except FileNotFoundError as exc:
            LOGGER.error("%s", exc)
            emit_if_present(self.event_bus, "error", str(exc), direction="error")
            return "", str(exc)
        LOGGER.debug("Running Codex %s command: %s", label, " ".join(args))
        try:
            completed = subprocess.run(
                args,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                cwd=self.root_dir,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            LOGGER.error("Codex %s timeout after %s seconds", label, self.timeout_seconds)
            emit_if_present(self.event_bus, "error", f"Codex timeout after {self.timeout_seconds} seconds", direction="error")
            return "", f"timeout after {self.timeout_seconds} seconds: {exc}"
        except OSError as exc:
            message = _codex_not_found_message(self.command) if getattr(exc, "winerror", None) == 2 else str(exc)
            LOGGER.error("Codex %s start failed: %s", label, message)
            emit_if_present(self.event_bus, "error", message, direction="error")
            return "", message

        if completed.stderr.strip():
            LOGGER.debug("Codex %s stderr: %s", label, completed.stderr.strip()[-4000:])
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[-1000:]
            message = f"Codex exited with code {completed.returncode}: {stderr}" if stderr else f"Codex exited with code {completed.returncode}"
            LOGGER.error("Codex %s failed: %s", label, message)
            emit_if_present(self.event_bus, "error", message, direction="error")
            return "", message

        return completed.stdout.strip(), None

    def _build_args(self) -> list[str]:
        executable = _resolve_command_executable(self.command)
        if executable is None:
            raise FileNotFoundError(_codex_not_found_message(self.command))
        base = _split_command(self.command)
        base[0] = executable
        return [
            *base,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--cd",
            str(self.root_dir),
            "--color",
            "never",
            "-",
        ]


def _split_command(command: str) -> list[str]:
    raw = command.strip().strip('"')
    if Path(raw).exists():
        return [raw]
    parts = shlex.split(command, posix=os.name != "nt")
    return [part.strip('"') for part in parts]


def _resolve_command_executable(command: str) -> str | None:
    parts = _split_command(command)
    if not parts:
        return None
    executable = parts[0]
    path = Path(executable)
    if path.exists():
        return str(path)
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    return None


def _codex_not_found_message(command: str) -> str:
    return (
        "Не найдена команда Codex. Проверь codex.command в config.yaml. "
        "На Ubuntu убедись, что Codex CLI установлен и доступен в PATH."
    )


def _decision_from_json(data: dict[str, Any]) -> DecisionResult:
    priority = str(data.get("priority", "normal")).lower()
    if priority not in {"low", "normal", "high", "urgent"}:
        priority = "normal"
    confidence = float(data.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))
    return DecisionResult(
        notify=bool(data.get("notify", False)),
        confidence=confidence,
        reason=str(data.get("reason", "")).strip()[:1000],
        priority=priority,
        suggested_action=str(data.get("suggested_action", "")).strip()[:1000],
        summary=str(data.get("summary", "")).strip()[:1000],
        source="codex",
    )


def _batch_decision_from_json(data: dict[str, Any]) -> BatchDecisionResult:
    raw_items = data.get("items", [])
    items: dict[int, DecisionResult] = {}
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                message_id = int(item.get("message_id"))
            except (TypeError, ValueError):
                continue
            items[message_id] = _decision_from_json(item)
    context_request = _context_request_from_json(data.get("context_request"))
    return BatchDecisionResult(
        items=items,
        batch_summary=str(data.get("batch_summary", "")).strip()[:1500],
        need_more_context=bool(data.get("need_more_context", False)),
        context_request=context_request,
    )


def _context_request_from_json(value: Any) -> ContextRequest | None:
    if not isinstance(value, dict):
        return None
    keywords_raw = value.get("keywords") or []
    keywords = [str(item).strip() for item in keywords_raw if str(item).strip()] if isinstance(keywords_raw, list) else []
    try:
        chat_id = int(value["chat_id"]) if value.get("chat_id") is not None else None
    except (TypeError, ValueError):
        chat_id = None
    try:
        before_message_id = int(value["before_message_id"]) if value.get("before_message_id") is not None else None
    except (TypeError, ValueError):
        before_message_id = None
    try:
        limit = int(value.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return ContextRequest(
        chat_id=chat_id,
        before_message_id=before_message_id,
        limit=max(1, min(limit, 100)),
        keywords=keywords[:12],
    )


def _fallback_result(error: str) -> DecisionResult:
    return DecisionResult(
        notify=False,
        confidence=0.0,
        reason="Ne udalos nadezhno klassifitsirovat soobschenie.",
        priority="normal",
        suggested_action="Proverit log i pri neobhodimosti soobschenie vruchnuyu.",
        summary="Klassifikatsiya ne vypolnena.",
        source="codex",
        classification_error=error,
    )


def _limit_prompt(prompt: str, max_chars: int) -> str:
    if len(prompt) <= max_chars:
        return prompt
    return prompt[-max_chars:]


def _extract_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty Codex output")
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : index + 1]
                    loaded = json.loads(candidate)
                    if isinstance(loaded, dict):
                        return loaded
        start = raw.find("{", start + 1)
    raise ValueError("JSON object not found")
