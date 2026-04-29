from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from secretary.bot_runner import BotRunner
from secretary.events import BotEvent, EventBus
from secretary.gui_app import EventBridge, LogWindow


class SecretaryTrayApp(QObject):
    def __init__(self, app: QApplication, runtime_dir: Path, config_path: Path, auto_start: bool = True) -> None:
        super().__init__()
        self.app = app
        self.runtime_dir = runtime_dir
        self.config_path = config_path
        self.context_path = runtime_dir / "context.md"
        self.logs_dir = runtime_dir / "logs"
        self.event_bus = EventBus()
        self.runner = BotRunner(config_path, self.event_bus)
        self.window = LogWindow(self.event_bus, self.runner, self.logs_dir / "secretary.log")
        self.status = "остановлен"

        self.tray = QSystemTrayIcon()
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_activated)
        self.tray.show()
        self._set_status("остановлен")

        self.bridge = EventBridge(self.event_bus)
        self.bridge.event_received.connect(self._on_event)

        if not config_path.exists():
            self._set_status("ошибка")
            QMessageBox.critical(
                None,
                "Telegram Secretary Bot",
                f"Не найден config.yaml рядом с приложением:\n{config_path}",
            )
        elif auto_start:
            self.start_bot()

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        open_window = QAction("Открыть окно", self)
        start_bot = QAction("Запустить бота", self)
        stop_bot = QAction("Остановить бота", self)
        restart_bot = QAction("Перезапустить бота", self)
        open_config = QAction("Открыть config.yaml", self)
        open_context = QAction("Открыть context.md", self)
        open_logs = QAction("Открыть папку логов", self)
        exit_app = QAction("Выход", self)

        open_window.triggered.connect(self.show_window)
        start_bot.triggered.connect(self.start_bot)
        stop_bot.triggered.connect(self.stop_bot)
        restart_bot.triggered.connect(self.restart_bot)
        open_config.triggered.connect(lambda: self._open_path(self.config_path))
        open_context.triggered.connect(lambda: self._open_path(self.context_path))
        open_logs.triggered.connect(lambda: self._open_path(self.logs_dir))
        exit_app.triggered.connect(self.quit)

        for action in (open_window, start_bot, stop_bot, restart_bot):
            menu.addAction(action)
        menu.addSeparator()
        for action in (open_config, open_context, open_logs):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(exit_app)
        return menu

    @Slot()
    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    @Slot()
    def start_bot(self) -> None:
        if self.runner.start():
            self._set_status("работает")

    @Slot()
    def stop_bot(self) -> None:
        if self.runner.stop():
            self._set_status("остановлен")
        else:
            self._set_status("ошибка")

    @Slot()
    def restart_bot(self) -> None:
        if self.runner.restart():
            self._set_status("работает")
        else:
            self._set_status("ошибка")

    @Slot()
    def quit(self) -> None:
        self.runner.stop()
        self.tray.hide()
        self.app.quit()

    @Slot(object)
    def _on_event(self, event: BotEvent) -> None:
        if event.kind == "error":
            self._set_status("ошибка")
        elif self.runner.is_running() and self.status != "ошибка":
            self._set_status("работает")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def _set_status(self, status: str) -> None:
        self.status = status
        self.tray.setToolTip(f"Telegram Secretary Bot: {status}")
        self.tray.setIcon(_status_icon(status))

    def _open_path(self, path: Path) -> None:
        if path.suffix:
            if not path.exists():
                QMessageBox.warning(None, "Telegram Secretary Bot", f"Файл не найден:\n{path}")
                return
        else:
            path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)


def _status_icon(status: str) -> QIcon:
    color = QColor("#2e7d32")
    if status == "остановлен":
        color = QColor("#757575")
    elif status == "ошибка":
        color = QColor("#c62828")

    pixmap = QPixmap(QSize(64, 64))
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(color.darker(130))
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pixmap)
