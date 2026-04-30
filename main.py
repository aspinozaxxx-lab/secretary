from __future__ import annotations

import argparse
import sys
from pathlib import Path

from secretary.app import SecretaryApp
from secretary.config import load_config
from secretary.database import ChatDatabase
from secretary.export_importer import import_telegram_export, inspect_export


def main() -> int:
    args = _parse_args()
    command = args.command or "run"
    if command == "run":
        return _run_bot(Path(args.config))
    if command == "db-status":
        return _db_status(Path(args.config))
    if command == "import-telegram-export":
        return _import_export(Path(args.config), Path(args.path) if args.path else None)
    raise ValueError(f"Unknown command: {command}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram Secretary Bot")
    parser.add_argument(
        "--config",
        dest="root_config",
        default="config.yaml",
        help="Path to config.yaml",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run Telegram polling bot")
    run_parser.add_argument("--config", dest="command_config", default=None, help="Path to config.yaml")

    import_parser = subparsers.add_parser("import-telegram-export", help="Import Telegram export into SQLite")
    import_parser.add_argument("--config", dest="command_config", default=None, help="Path to config.yaml")
    import_parser.add_argument("--path", default=None, help="Path to Telegram export directory")

    status_parser = subparsers.add_parser("db-status", help="Show SQLite database status")
    status_parser.add_argument("--config", dest="command_config", default=None, help="Path to config.yaml")

    args = parser.parse_args()
    args.config = getattr(args, "command_config", None) or args.root_config
    return args


def _run_bot(config_path: Path) -> int:
    app = SecretaryApp(config_path)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nОстановка по Ctrl+C...")
        app.stop()
    return 0


def _db_status(config_path: Path) -> int:
    config = load_config(config_path)
    database = _open_database(config)
    stats = database.stats()
    print(f"path: {stats.path}")
    print(f"media_dir: {stats.media_dir}")
    print(f"chats: {stats.chats}")
    print(f"messages: {stats.messages}")
    print(f"attachments: {stats.attachments}")
    print(f"fts_enabled: {'yes' if stats.fts_enabled else 'no'}")
    print(f"last_import_at: {stats.last_import_at or 'none'}")
    print(f"last_import_summary: {stats.last_import_summary or 'none'}")
    return 0


def _import_export(config_path: Path, export_path: Path | None) -> int:
    config = load_config(config_path)
    path = export_path or config.telegram_export.import_dir
    if path is None:
        raise ValueError("Telegram export path is not set. Use --path or telegram_export.import_dir.")
    database = _open_database(config)
    inspection = inspect_export(path)
    print(f"export_path: {inspection.get('path')}")
    print(f"chat_dirs: {len(inspection.get('chat_dirs') or [])}")
    print(f"extensions: {inspection.get('extensions')}")
    result = import_telegram_export(path, database)
    print(f"imported_chats: {result.chats}")
    print(f"imported_messages: {result.messages}")
    print(f"imported_attachments: {result.attachments}")
    print(f"files_seen: {result.files_seen}")
    return 0


def _open_database(config) -> ChatDatabase:
    if not config.database.enabled:
        raise ValueError("Database is disabled in config.")
    database = ChatDatabase(
        config.database.path or (config.root_dir / "chat_history.sqlite3"),
        config.database.media_dir or (config.root_dir / "media"),
        config.database.fts_enabled,
    )
    database.init_db()
    return database


if __name__ == "__main__":
    sys.exit(main())
