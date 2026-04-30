from __future__ import annotations

import hashlib
import html
import mimetypes
import re
import shutil
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from secretary.database import ChatDatabase


@dataclass(slots=True)
class ImportResult:
    chats: int = 0
    messages: int = 0
    attachments: int = 0
    files_seen: int = 0
    source: str = "telegram_export"


@dataclass(slots=True)
class ExportMessage:
    chat_id: int
    chat_title: str
    message_id: int
    date: str | None
    sender_name: str | None
    text: str
    reply_to_message_id: int | None = None
    attachments: list[Path] = field(default_factory=list)
    source_file: Path | None = None


def import_telegram_export(export_dir: Path, database: ChatDatabase) -> ImportResult:
    export_dir = export_dir.resolve()
    if not export_dir.exists():
        raise FileNotFoundError(f"Telegram export path not found: {export_dir}")
    database.init_db()
    result = ImportResult()
    chat_dirs = _find_chat_dirs(export_dir)
    for chat_dir in chat_dirs:
        imported = _import_chat_dir(chat_dir, database)
        if imported.messages or imported.attachments:
            result.chats += imported.chats
            result.messages += imported.messages
            result.attachments += imported.attachments
            result.files_seen += imported.files_seen
    summary = (
        f"Imported chats={result.chats}, messages={result.messages}, "
        f"attachments={result.attachments}, files_seen={result.files_seen}"
    )
    database.record_import_status(
        source=result.source,
        import_dir=export_dir,
        chats=result.chats,
        messages=result.messages,
        attachments=result.attachments,
        summary=summary,
    )
    return result


def inspect_export(export_dir: Path) -> dict[str, Any]:
    export_dir = export_dir.resolve()
    if not export_dir.exists():
        return {"exists": False, "path": str(export_dir)}
    files = list(export_dir.rglob("*"))
    extensions: dict[str, int] = {}
    for item in files:
        if item.is_file():
            ext = item.suffix.lower() or "[no_ext]"
            extensions[ext] = extensions.get(ext, 0) + 1
    return {
        "exists": True,
        "path": str(export_dir),
        "chat_dirs": [str(item) for item in _find_chat_dirs(export_dir)],
        "extensions": dict(sorted(extensions.items())),
    }


def _find_chat_dirs(export_dir: Path) -> list[Path]:
    if (export_dir / "result.json").exists() or list(export_dir.glob("messages*.html")):
        return [export_dir]
    dirs = []
    for child in sorted(export_dir.iterdir()):
        if child.is_dir() and ((child / "result.json").exists() or list(child.glob("messages*.html"))):
            dirs.append(child)
    return dirs


def _import_chat_dir(chat_dir: Path, database: ChatDatabase) -> ImportResult:
    result = ImportResult()
    html_files = sorted(chat_dir.glob("messages*.html"), key=_html_sort_key)
    if not html_files:
        return result
    chat_title = _read_chat_title(html_files[0]) or chat_dir.name
    chat_id = _synthetic_chat_id(chat_title, chat_dir)
    database.upsert_chat(
        {
            "chat_id": chat_id,
            "type": "telegram_export",
            "title": chat_title,
            "username": None,
        },
        source="telegram_export",
    )
    result.chats = 1
    for html_file in html_files:
        parser = TelegramHtmlParser(chat_id=chat_id, chat_title=chat_title, source_file=html_file)
        parser.feed(html_file.read_text(encoding="utf-8-sig", errors="replace"))
        parser.close()
        for message in parser.messages:
            existed = database.has_message(message.chat_id, message.message_id, "telegram_export")
            db_id = database.insert_message_idempotent(
                chat_id=message.chat_id,
                message_id=message.message_id,
                update_id=None,
                date=message.date,
                sender_id=None,
                sender_username=None,
                sender_name=message.sender_name,
                text=message.text,
                reply_to_message_id=message.reply_to_message_id,
                has_attachment=1 if message.attachments else 0,
                source="telegram_export",
                source_file=str(html_file.relative_to(chat_dir.parent)),
                raw_json=None,
            )
            if db_id and not existed:
                result.messages += 1
            if existed:
                continue
            for attachment in message.attachments:
                result.files_seen += 1
                stored = _copy_attachment(attachment, chat_dir, database.media_dir, chat_id)
                if stored is None:
                    continue
                database.insert_attachment(
                    message_db_id=db_id,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    file_name=attachment.name,
                    original_path=str(attachment),
                    stored_path=stored,
                    mime_type=mimetypes.guess_type(attachment.name)[0],
                    size_bytes=attachment.stat().st_size if attachment.exists() else None,
                    kind=_attachment_kind(attachment),
                )
                result.attachments += 1
    return result


class TelegramHtmlParser(HTMLParser):
    def __init__(self, chat_id: int, chat_title: str, source_file: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.chat_id = chat_id
        self.chat_title = chat_title
        self.source_file = source_file
        self.messages: list[ExportMessage] = []
        self._message: dict[str, Any] | None = None
        self._message_depth = 0
        self._div_depth = 0
        self._field_stack: list[str] = []
        self._div_field_stack: list[str | None] = []
        self._last_sender: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set((attrs_dict.get("class") or "").split())
        if tag == "div":
            self._div_depth += 1
            field_marker: str | None = None
            if self._message is None and "message" in classes and "service" not in classes:
                msg_id = _message_id_from_attrs(attrs_dict)
                if msg_id is not None:
                    self._message = {
                        "message_id": msg_id,
                        "date": None,
                        "sender_name": None,
                        "text": [],
                        "reply_to_message_id": None,
                        "attachments": [],
                    }
                    self._message_depth = self._div_depth
            if self._message is not None:
                if "from_name" in classes:
                    field_marker = "from"
                    self._field_stack.append(field_marker)
                elif "text" in classes:
                    field_marker = "text"
                    self._field_stack.append(field_marker)
                elif "reply_to" in classes:
                    field_marker = "reply"
                    self._field_stack.append(field_marker)
                elif "date" in classes and "details" in classes:
                    self._message["date"] = _parse_telegram_date(attrs_dict.get("title"))
                self._div_field_stack.append(field_marker)
        if tag == "br" and self._current_field() == "text" and self._message is not None:
            self._message["text"].append("\n")
        if tag == "a" and self._message is not None:
            href = attrs_dict.get("href") or ""
            if href.startswith("#go_to_message"):
                self._message["reply_to_message_id"] = _int_or_none(href.replace("#go_to_message", ""))
            attachment = _local_attachment_path(self.source_file.parent, href)
            if attachment is not None:
                self._message["attachments"].append(attachment)
        if tag == "img" and self._message is not None:
            src = attrs_dict.get("src") or ""
            attachment = _local_attachment_path(self.source_file.parent, src)
            if attachment is not None and "emoji" not in src and "sticker" not in src:
                self._message["attachments"].append(attachment)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._message is not None and self._div_depth == self._message_depth:
                self._finish_message()
            field_marker = self._div_field_stack.pop() if self._div_field_stack else None
            if field_marker is not None and self._field_stack:
                self._field_stack.pop()
            self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._message is None:
            return
        field = self._current_field()
        if field == "from":
            name = _normalize_text(data)
            if name:
                self._message["sender_name"] = name
        elif field == "text":
            self._message["text"].append(data)

    def _current_field(self) -> str | None:
        return self._field_stack[-1] if self._field_stack else None

    def _finish_message(self) -> None:
        if self._message is None:
            return
        sender = self._message.get("sender_name") or self._last_sender
        if sender:
            self._last_sender = sender
        text = _normalize_text("".join(self._message.get("text") or []))
        attachments = _dedupe_paths(self._message.get("attachments") or [])
        if text or attachments:
            self.messages.append(
                ExportMessage(
                    chat_id=self.chat_id,
                    chat_title=self.chat_title,
                    message_id=int(self._message["message_id"]),
                    date=self._message.get("date"),
                    sender_name=sender,
                    text=text,
                    reply_to_message_id=self._message.get("reply_to_message_id"),
                    attachments=attachments,
                    source_file=self.source_file,
                )
            )
        self._message = None
        self._message_depth = 0
        self._field_stack.clear()
        self._div_field_stack.clear()


def _read_chat_title(html_file: Path) -> str | None:
    text = html_file.read_text(encoding="utf-8-sig", errors="replace")
    match = re.search(r'<div class="text bold">\s*(.*?)\s*</div>', text, flags=re.S)
    if not match:
        return None
    return _normalize_text(re.sub(r"<.*?>", "", html.unescape(match.group(1))))


def _message_id_from_attrs(attrs: dict[str, str]) -> int | None:
    raw = attrs.get("id") or ""
    match = re.search(r"message(\d+)", raw)
    return int(match.group(1)) if match else None


def _parse_telegram_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2}) UTC([+-]\d{2}):?(\d{2})", value)
    if not match:
        return value
    day, month, year, hour, minute, second, tz_hour, tz_minute = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}{tz_hour}:{tz_minute}"


def _local_attachment_path(base_dir: Path, value: str) -> Path | None:
    if not value or value.startswith(("http://", "https://", "tg://", "#")):
        return None
    clean = value.split("?", maxsplit=1)[0].replace("\\", "/")
    if not clean or clean.startswith(("css/", "js/", "images/")):
        return None
    path = (base_dir / clean).resolve()
    try:
        path.relative_to(base_dir.resolve())
    except ValueError:
        return None
    if path.exists() and path.is_file():
        return path
    return None


def _copy_attachment(path: Path, chat_dir: Path, media_dir: Path, chat_id: int) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        relative = path.relative_to(chat_dir)
    except ValueError:
        relative = Path(path.name)
    safe_parts = [_safe_name(part) for part in relative.parts]
    target_rel = Path(str(chat_id), *safe_parts)
    target = media_dir / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != path.stat().st_size:
        shutil.copy2(path, target)
    return target_rel.as_posix()


def _attachment_kind(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return "file"


def _html_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"messages(\d*)\.html", path.name)
    if not match:
        return (999999, path.name)
    number = int(match.group(1) or 1)
    return (number, path.name)


def _synthetic_chat_id(chat_title: str, chat_dir: Path) -> int:
    raw = f"{chat_title}|{chat_dir.name}".encode("utf-8", errors="ignore")
    return -int(zlib.crc32(raw) or 1)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if not cleaned:
        digest = hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"file_{digest}"
    return cleaned[:120]


def _normalize_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(value)).strip()


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result = []
    seen = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result
