from __future__ import annotations

import logging
from pathlib import Path


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, _mask_secret(secret))
        record.msg = message
        record.args = ()
        return True


def setup_logging(level: str, log_file: Path, secrets: list[str] | None = None) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redacting_filter = RedactingFilter(secrets or [])

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redacting_filter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8-sig")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redacting_filter)

    root.addHandler(console)
    root.addHandler(file_handler)


def _mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"
