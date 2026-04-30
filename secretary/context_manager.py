from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CONTEXT_FILE_NAME = "context.md"


@dataclass(slots=True)
class ContextUpdateResult:
    backup_path: Path | None
    size_bytes: int


def is_context_file_name(file_name: str | None) -> bool:
    if not file_name:
        return False
    return Path(file_name).name == CONTEXT_FILE_NAME and file_name == CONTEXT_FILE_NAME


def decode_context_bytes(content: bytes, max_bytes: int) -> str:
    if len(content) > max_bytes:
        raise ValueError(f"Файл слишком большой: максимум {max_bytes} байт.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Файл должен быть в UTF-8 или UTF-8 with BOM.") from exc
    if not text.strip():
        raise ValueError("Файл context.md пустой.")
    return text


def replace_context_file(context_path: Path, backup_dir: Path, text: str) -> ContextUpdateResult:
    context_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if context_path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"context_{stamp}.md"
        shutil.copy2(context_path, backup_path)

    tmp_path = context_path.with_name(f".{context_path.name}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8-sig")
        os.replace(tmp_path, context_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return ContextUpdateResult(backup_path=backup_path, size_bytes=len(text.encode("utf-8-sig")))
