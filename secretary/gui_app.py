from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from secretary.bot_runner import BotRunner
from secretary.events import BotEvent, EventBus


class EventBridge(QObject):
    event_received = Signal(object)

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        event_bus.subscribe(self.event_received.emit)


class LogWindow(QMainWindow):
    def __init__(self, event_bus: EventBus, runner: BotRunner, log_file: Path) -> None:
        super().__init__()
        self.runner = runner
        self.log_file = log_file
        self.setWindowTitle("Telegram Secretary Bot")
        self.resize(1100, 620)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Время", "Тип", "Чат", "Автор", "Текст", "Решение"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        clear_button = QPushButton("Очистить экранный лог")
        open_log_button = QPushButton("Открыть полный лог-файл")
        restart_button = QPushButton("Перезапустить бота")
        clear_button.clicked.connect(lambda: self.table.setRowCount(0))
        open_log_button.clicked.connect(self.open_log_file)
        restart_button.clicked.connect(self.runner.restart)

        buttons = QHBoxLayout()
        buttons.addWidget(clear_button)
        buttons.addWidget(open_log_button)
        buttons.addWidget(restart_button)
        buttons.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(buttons)

        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.bridge = EventBridge(event_bus)
        self.bridge.event_received.connect(self.add_event)

    def closeEvent(self, event: object) -> None:
        self.hide()
        event.ignore()

    def changeEvent(self, event: object) -> None:
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.hide()
            event.ignore()
            return
        super().changeEvent(event)

    @Slot(object)
    def add_event(self, event: BotEvent) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            event.timestamp,
            event.kind,
            event.chat_title or (str(event.chat_id) if event.chat_id is not None else ""),
            event.author or "",
            event.text,
            _decision_text(event),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, column, item)
        self.table.scrollToBottom()

    @Slot()
    def open_log_file(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            self.log_file.write_text("", encoding="utf-8-sig")
        os.startfile(self.log_file)


def _decision_text(event: BotEvent) -> str:
    parts: list[str] = []
    if event.notify is not None:
        parts.append(f"notify={event.notify}")
    if event.priority:
        parts.append(event.priority)
    if event.reason:
        parts.append(event.reason)
    return " | ".join(parts)
