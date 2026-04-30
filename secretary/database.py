from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from secretary.models import ChatHistoryEntry, TelegramChat, TelegramMessage, TelegramUser


@dataclass(slots=True)
class DatabaseStats:
    path: Path
    media_dir: Path
    chats: int
    messages: int
    attachments: int
    fts_enabled: bool
    last_import_source: str | None = None
    last_import_at: str | None = None
    last_import_summary: str | None = None


@dataclass(slots=True)
class StoredMessage:
    id: int
    chat_id: int
    chat_title: str | None
    message_id: int | None
    date: str | None
    sender_name: str | None
    sender_username: str | None
    text: str
    source: str
    attachments: list[str]


class ChatDatabase:
    def __init__(self, path: Path, media_dir: Path, fts_enabled: bool = True) -> None:
        self.path = path
        self.media_dir = media_dir
        self.requested_fts_enabled = fts_enabled
        self.fts_enabled = False

    def init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    type TEXT,
                    title TEXT,
                    username TEXT,
                    first_seen_at TEXT,
                    last_seen_at TEXT,
                    source TEXT
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    display_name TEXT,
                    last_seen_at TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    update_id INTEGER,
                    date TEXT,
                    sender_id INTEGER,
                    sender_username TEXT,
                    sender_name TEXT,
                    text TEXT,
                    reply_to_message_id INTEGER,
                    has_attachment INTEGER DEFAULT 0,
                    source TEXT,
                    source_file TEXT,
                    raw_json TEXT,
                    created_at TEXT,
                    UNIQUE(chat_id, message_id, source)
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_db_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    file_name TEXT,
                    original_path TEXT,
                    stored_path TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    kind TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    import_dir TEXT,
                    imported_at TEXT,
                    chats INTEGER,
                    messages INTEGER,
                    attachments INTEGER,
                    summary TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON messages(chat_id, date);
                CREATE INDEX IF NOT EXISTS idx_messages_chat_message ON messages(chat_id, message_id);
                CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
                CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_name);
                CREATE INDEX IF NOT EXISTS idx_attachments_chat_message ON attachments(chat_id, message_id);
                """
            )
            self.fts_enabled = self._ensure_fts(conn)

    def upsert_chat(self, chat: TelegramChat | dict[str, Any], source: str = "bot", seen_at: str | None = None) -> None:
        item = _chat_dict(chat)
        now = seen_at or _now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO chats(chat_id, type, title, username, first_seen_at, last_seen_at, source)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    type=excluded.type,
                    title=COALESCE(excluded.title, chats.title),
                    username=COALESCE(excluded.username, chats.username),
                    last_seen_at=excluded.last_seen_at,
                    source=COALESCE(chats.source, excluded.source)
                """,
                (
                    item["chat_id"],
                    item.get("type"),
                    item.get("title"),
                    item.get("username"),
                    now,
                    now,
                    source,
                ),
            )

    def upsert_user(self, user: TelegramUser | dict[str, Any] | None, seen_at: str | None = None) -> None:
        if user is None:
            return
        item = _user_dict(user)
        if item["user_id"] is None:
            return
        now = seen_at or _now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, username, first_name, last_name, display_name, last_seen_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=COALESCE(excluded.username, users.username),
                    first_name=COALESCE(excluded.first_name, users.first_name),
                    last_name=COALESCE(excluded.last_name, users.last_name),
                    display_name=COALESCE(excluded.display_name, users.display_name),
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    item["user_id"],
                    item.get("username"),
                    item.get("first_name"),
                    item.get("last_name"),
                    item.get("display_name"),
                    now,
                ),
            )

    def insert_telegram_message(self, message: TelegramMessage) -> int:
        date = datetime.fromtimestamp(message.date, tz=timezone.utc).isoformat() if message.date else None
        sender = message.sender
        self.upsert_chat(message.chat, source="bot", seen_at=date)
        self.upsert_user(sender, seen_at=date)
        raw_json = json.dumps(message.raw, ensure_ascii=False) if message.raw else None
        attachment_summary = _telegram_attachment_summary(message)
        return self.insert_message_idempotent(
            chat_id=message.chat.chat_id,
            message_id=message.message_id,
            update_id=message.update_id,
            date=date,
            sender_id=sender.user_id if sender else None,
            sender_username=sender.username if sender else None,
            sender_name=sender.full_name if sender else None,
            text=message.text or "",
            reply_to_message_id=message.reply_to_message_id,
            has_attachment=1 if message.has_attachments else 0,
            source="bot",
            source_file=None,
            raw_json=raw_json,
            attachment_summary=attachment_summary,
        )

    def insert_message_idempotent(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        update_id: int | None,
        date: str | None,
        sender_id: int | None,
        sender_username: str | None,
        sender_name: str | None,
        text: str,
        reply_to_message_id: int | None,
        has_attachment: int,
        source: str,
        source_file: str | None,
        raw_json: str | None,
        attachment_summary: str | None = None,
    ) -> int:
        created_at = _now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO messages(
                    chat_id, message_id, update_id, date, sender_id, sender_username, sender_name,
                    text, reply_to_message_id, has_attachment, source, source_file, raw_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    update_id,
                    date,
                    sender_id,
                    sender_username,
                    sender_name,
                    text,
                    reply_to_message_id,
                    has_attachment,
                    source,
                    source_file,
                    raw_json,
                    created_at,
                ),
            )
            message_db_id = int(cursor.lastrowid or 0)
            if message_db_id == 0:
                row = conn.execute(
                    "SELECT id FROM messages WHERE chat_id=? AND message_id IS ? AND source=?",
                    (chat_id, message_id, source),
                ).fetchone()
                message_db_id = int(row["id"]) if row else 0
            else:
                self._upsert_fts(conn, message_db_id)
                if attachment_summary:
                    self.insert_attachment(
                        message_db_id=message_db_id,
                        chat_id=chat_id,
                        message_id=message_id,
                        file_name=attachment_summary,
                        original_path=None,
                        stored_path=None,
                        mime_type=None,
                        size_bytes=None,
                        kind="telegram_attachment",
                        conn=conn,
                    )
            return message_db_id

    def has_message(self, chat_id: int, message_id: int | None, source: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE chat_id=? AND message_id IS ? AND source=? LIMIT 1",
                (chat_id, message_id, source),
            ).fetchone()
            return row is not None

    def insert_attachment(
        self,
        *,
        message_db_id: int,
        chat_id: int,
        message_id: int | None,
        file_name: str | None,
        original_path: str | None,
        stored_path: str | None,
        mime_type: str | None,
        size_bytes: int | None,
        kind: str | None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        created_at = _now_iso()
        close_conn = conn is None
        connection = conn or self._connect()
        try:
            cursor = connection.execute(
                """
                INSERT INTO attachments(
                    message_db_id, chat_id, message_id, file_name, original_path, stored_path,
                    mime_type, size_bytes, kind, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_db_id,
                    chat_id,
                    message_id,
                    file_name,
                    original_path,
                    stored_path,
                    mime_type,
                    size_bytes,
                    kind,
                    created_at,
                ),
            )
            if close_conn:
                connection.commit()
            return int(cursor.lastrowid)
        finally:
            if close_conn:
                connection.close()

    def search_messages(self, query: str, limit: int = 20, chat_ids: list[int] | None = None) -> list[StoredMessage]:
        query = query.strip()
        if not query:
            return []
        with self._connection() as conn:
            if self.fts_enabled:
                rows = self._search_fts(conn, query, limit, chat_ids)
            else:
                rows = self._search_like(conn, query, limit, chat_ids)
            return [self._row_to_message(conn, row) for row in rows]

    def get_recent_messages(
        self,
        limit: int = 50,
        chat_ids: list[int] | None = None,
        since_iso: str | None = None,
        include_private: bool = False,
    ) -> list[StoredMessage]:
        params: list[Any] = []
        where = []
        if chat_ids:
            where.append(f"m.chat_id IN ({','.join('?' for _ in chat_ids)})")
            params.extend(chat_ids)
        if since_iso:
            where.append("m.date >= ?")
            params.append(since_iso)
        if not include_private:
            where.append("COALESCE(c.type, '') != 'private'")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*, c.title AS chat_title
                FROM messages m
                LEFT JOIN chats c ON c.chat_id = m.chat_id
                {where_sql}
                ORDER BY COALESCE(m.date, m.created_at) DESC, m.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [self._row_to_message(conn, row) for row in rows]

    def get_messages_around(self, chat_id: int, before_message_id: int | None, limit: int = 50) -> list[ChatHistoryEntry]:
        params: list[Any] = [chat_id]
        where = "m.chat_id = ?"
        if before_message_id is not None:
            where += " AND (m.message_id IS NULL OR m.message_id < ?)"
            params.append(before_message_id)
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*, c.title AS chat_title
                FROM messages m
                LEFT JOIN chats c ON c.chat_id = m.chat_id
                WHERE {where}
                ORDER BY COALESCE(m.date, m.created_at) DESC, m.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        entries = [
            ChatHistoryEntry(
                chat_id=int(row["chat_id"]),
                chat_title=row["chat_title"],
                sender=row["sender_name"],
                text=row["text"] or "",
                date=_iso_to_timestamp(row["date"]),
                message_id=row["message_id"] or 0,
            )
            for row in reversed(rows)
        ]
        return entries

    def get_chat_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, type, title, username, first_seen_at, last_seen_at, source
                FROM chats
                ORDER BY COALESCE(last_seen_at, first_seen_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_chat_targets_by_keywords(self, keywords: list[str], limit: int = 10) -> list[dict[str, Any]]:
        terms = [term.lower() for term in keywords if len(term) >= 3]
        if not terms:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, type, title, username, first_seen_at, last_seen_at, source
                FROM chats
                ORDER BY COALESCE(last_seen_at, first_seen_at) DESC
                """
            ).fetchall()
        matches = []
        for row in rows:
            haystack = " ".join(str(row[key] or "") for key in ("title", "username", "chat_id")).lower()
            if any(term in haystack for term in terms):
                matches.append(dict(row))
            if len(matches) >= limit:
                break
        return matches

    def export_context_for_codex(
        self,
        *,
        title: str,
        targeted_chats: list[dict[str, Any]] | None,
        recent_messages: list[StoredMessage],
        search_hits: list[StoredMessage],
        max_chars: int = 12000,
    ) -> str:
        lines = [
            title,
            f"SQLite database path: {self.path}",
            f"Media dir: {self.media_dir}",
            f"FTS enabled: {'yes' if self.fts_enabled else 'no'}",
            "Bot gotovit vyborku sam; esli Codex mojet chitat fayly v read-only cwd, baza i media dostupny tolko dlya chteniya.",
            "",
            "Targeted chats:",
        ]
        chats = targeted_chats or []
        if chats:
            for chat in chats[:20]:
                lines.append(f"- {chat.get('chat_id')} | {chat.get('type')} | {chat.get('title') or chat.get('username') or 'bez nazvaniya'}")
        else:
            lines.append("- target chats ne opredeleny")
        lines.append("")
        lines.append("Search hits:")
        lines.extend(_format_stored_messages(search_hits[:40]))
        lines.append("")
        lines.append("Recent messages:")
        lines.extend(_format_stored_messages(recent_messages[:80]))
        text = "\n".join(lines)
        if len(text) > max_chars:
            suffix = "\n\n[SQLite context trimmed by size limit]"
            text = text[: max(0, max_chars - len(suffix))].rstrip() + suffix
        return text

    def stats(self) -> DatabaseStats:
        with self._connection() as conn:
            chats = int(conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0])
            messages = int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
            attachments = int(conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0])
            import_row = conn.execute(
                "SELECT source, imported_at, summary FROM imports ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return DatabaseStats(
            path=self.path,
            media_dir=self.media_dir,
            chats=chats,
            messages=messages,
            attachments=attachments,
            fts_enabled=self.fts_enabled,
            last_import_source=import_row["source"] if import_row else None,
            last_import_at=import_row["imported_at"] if import_row else None,
            last_import_summary=import_row["summary"] if import_row else None,
        )

    def record_import_status(
        self,
        *,
        source: str,
        import_dir: Path,
        chats: int,
        messages: int,
        attachments: int,
        summary: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO imports(source, import_dir, imported_at, chats, messages, attachments, summary)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (source, str(import_dir), _now_iso(), chats, messages, attachments, summary),
            )

    def get_import_status(self) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM imports ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_fts(self, conn: sqlite3.Connection) -> bool:
        if not self.requested_fts_enabled:
            return False
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
                    text,
                    sender_name,
                    chat_title,
                    content='messages',
                    content_rowid='id'
                )
                """
            )
        except sqlite3.Error:
            return False
        return True

    def _upsert_fts(self, conn: sqlite3.Connection, message_db_id: int) -> None:
        if not self.fts_enabled:
            return
        row = conn.execute(
            """
            SELECT m.id, m.text, m.sender_name, c.title AS chat_title
            FROM messages m
            LEFT JOIN chats c ON c.chat_id = m.chat_id
            WHERE m.id=?
            """,
            (message_db_id,),
        ).fetchone()
        if row is None:
            return
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO message_fts(rowid, text, sender_name, chat_title)
                VALUES(?, ?, ?, ?)
                """,
                (row["id"], row["text"] or "", row["sender_name"] or "", row["chat_title"] or ""),
            )
        except sqlite3.Error:
            self.fts_enabled = False

    def _search_fts(
        self,
        conn: sqlite3.Connection,
        query: str,
        limit: int,
        chat_ids: list[int] | None,
    ) -> list[sqlite3.Row]:
        match_query = " OR ".join(_fts_token(token) for token in _keywords(query)[:8])
        if not match_query:
            return []
        params: list[Any] = [match_query]
        where = "message_fts MATCH ?"
        if chat_ids:
            where += f" AND m.chat_id IN ({','.join('?' for _ in chat_ids)})"
            params.extend(chat_ids)
        params.append(limit)
        try:
            return conn.execute(
                f"""
                SELECT m.*, c.title AS chat_title
                FROM message_fts
                JOIN messages m ON m.id = message_fts.rowid
                LEFT JOIN chats c ON c.chat_id = m.chat_id
                WHERE {where}
                ORDER BY COALESCE(m.date, m.created_at) DESC, m.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.Error:
            self.fts_enabled = False
            return self._search_like(conn, query, limit, chat_ids)

    def _search_like(
        self,
        conn: sqlite3.Connection,
        query: str,
        limit: int,
        chat_ids: list[int] | None,
    ) -> list[sqlite3.Row]:
        terms = _keywords(query)[:8] or [query]
        params: list[Any] = []
        clauses = []
        for term in terms:
            clauses.append("(LOWER(m.text) LIKE ? OR LOWER(m.sender_name) LIKE ? OR LOWER(c.title) LIKE ?)")
            value = f"%{term.lower()}%"
            params.extend([value, value, value])
        where = " OR ".join(clauses)
        if chat_ids:
            where = f"({where}) AND m.chat_id IN ({','.join('?' for _ in chat_ids)})"
            params.extend(chat_ids)
        params.append(limit)
        return conn.execute(
            f"""
            SELECT m.*, c.title AS chat_title
            FROM messages m
            LEFT JOIN chats c ON c.chat_id = m.chat_id
            WHERE {where}
            ORDER BY COALESCE(m.date, m.created_at) DESC, m.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def _row_to_message(self, conn: sqlite3.Connection, row: sqlite3.Row) -> StoredMessage:
        attachment_rows = conn.execute(
            "SELECT stored_path, file_name FROM attachments WHERE message_db_id=? ORDER BY id LIMIT 5",
            (row["id"],),
        ).fetchall()
        attachments = [
            str(item["stored_path"] or item["file_name"] or "").strip()
            for item in attachment_rows
            if str(item["stored_path"] or item["file_name"] or "").strip()
        ]
        return StoredMessage(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            chat_title=row["chat_title"],
            message_id=row["message_id"],
            date=row["date"],
            sender_name=row["sender_name"],
            sender_username=row["sender_username"],
            text=row["text"] or "",
            source=row["source"] or "",
            attachments=attachments,
        )


def _format_stored_messages(messages: list[StoredMessage]) -> list[str]:
    if not messages:
        return ["- net dannyh"]
    lines = []
    for message in messages:
        chat = message.chat_title or str(message.chat_id)
        sender = message.sender_name or message.sender_username or "unknown"
        text = _one_line(message.text or "[net teksta]")
        attach = f" attachments={', '.join(message.attachments)}" if message.attachments else ""
        lines.append(f"- [{message.date or 'no-date'}] {chat} | {sender}: {text}{attach}")
    return lines


def _chat_dict(chat: TelegramChat | dict[str, Any]) -> dict[str, Any]:
    if isinstance(chat, TelegramChat):
        return {
            "chat_id": chat.chat_id,
            "type": chat.chat_type,
            "title": chat.title,
            "username": chat.username,
        }
    return chat


def _user_dict(user: TelegramUser | dict[str, Any]) -> dict[str, Any]:
    if isinstance(user, TelegramUser):
        return {
            "user_id": user.user_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.full_name,
        }
    return user


def _telegram_attachment_summary(message: TelegramMessage) -> str | None:
    if message.document_file_name:
        return message.document_file_name
    if message.has_attachments:
        return "telegram_attachment"
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_to_timestamp(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _keywords(text: str) -> list[str]:
    return [item.lower() for item in re.findall(r"[\wА-Яа-яЁё-]{3,}", text, flags=re.UNICODE)]


def _fts_token(token: str) -> str:
    cleaned = re.sub(r"[^\wА-Яа-яЁё-]", "", token, flags=re.UNICODE)
    return f'"{cleaned}"' if cleaned else '""'


def _one_line(text: str, limit: int = 300) -> str:
    result = re.sub(r"\s+", " ", text).strip()
    if len(result) > limit:
        return result[: limit - 1].rstrip() + "…"
    return result
