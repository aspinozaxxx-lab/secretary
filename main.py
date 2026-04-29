from __future__ import annotations

import argparse
import sys
from pathlib import Path

from secretary.app import SecretaryApp


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Secretary Bot")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml",
    )
    args = parser.parse_args()

    app = SecretaryApp(Path(args.config))
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nОстановка по Ctrl+C...")
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
