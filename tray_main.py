from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from secretary.tray_app import SecretaryTrayApp


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    root = runtime_dir()
    tray = SecretaryTrayApp(app, root, root / "config.yaml")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
