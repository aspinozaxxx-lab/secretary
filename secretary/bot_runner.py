from __future__ import annotations

import threading
from pathlib import Path

from secretary.app import SecretaryApp
from secretary.events import EventBus, emit_if_present


class BotRunner:
    def __init__(self, config_path: Path, event_bus: EventBus, stop_timeout_seconds: int = 4) -> None:
        self.config_path = config_path
        self.event_bus = event_bus
        self.stop_timeout_seconds = stop_timeout_seconds
        self.last_error: str | None = None
        self._app: SecretaryApp | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._lock = threading.RLock()

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                emit_if_present(self.event_bus, "system", "Бот уже запущен", direction="system")
                return True
            self.last_error = None
            self._stop_requested = False
            self._thread = threading.Thread(target=self._run, name="SecretaryBotPolling", daemon=True)
            self._thread.start()
            emit_if_present(self.event_bus, "system", "Запуск бота", direction="system")
            return True

    def stop(self) -> bool:
        with self._lock:
            app = self._app
            thread = self._thread
        if thread is None:
            emit_if_present(self.event_bus, "system", "Бот уже остановлен", direction="system")
            return True
        emit_if_present(self.event_bus, "system", "Остановка бота", direction="system")
        with self._lock:
            self._stop_requested = True
        if app is not None:
            app.stop()
        thread.join(timeout=self.stop_timeout_seconds)
        if thread.is_alive():
            self.last_error = "Бот не остановился за отведенное время"
            emit_if_present(self.event_bus, "error", self.last_error, direction="error")
            return False
        with self._lock:
            self._app = None
            self._thread = None
        emit_if_present(self.event_bus, "system", "Бот остановлен", direction="system")
        return True

    def restart(self) -> bool:
        stopped = self.stop()
        started = self.start()
        return stopped and started

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run(self) -> None:
        try:
            app = SecretaryApp(self.config_path, event_bus=self.event_bus)
            with self._lock:
                self._app = app
                stop_requested = self._stop_requested
            if stop_requested:
                app.stop()
            app.run()
        except Exception as exc:
            self.last_error = str(exc)
            emit_if_present(self.event_bus, "error", f"Ошибка бота: {exc}", direction="error")
        finally:
            with self._lock:
                self._app = None
                self._thread = None
            emit_if_present(self.event_bus, "system", "Поток бота завершен", direction="system")
