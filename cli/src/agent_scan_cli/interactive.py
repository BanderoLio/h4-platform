from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .client import (
    DEFAULT_BASE_URL,
    ReportNotReady,
    ScanApiError,
    ScanAuthError,
    ScanClient,
    ScanFailed,
    ScanNotFound,
    default_report_path,
)
from .markdown import render_markdown
from .terminal import BLUE, DIM, GREEN, MAGENTA, Terminal


@dataclass
class InteractiveState:
    base_url: str
    timeout: float
    api_key: str | None = None
    last_scan_id: str | None = None


class InteractiveApp:
    def __init__(
        self,
        *,
        initial_base_url: str | None = None,
        initial_timeout: float = 30.0,
        initial_api_key: str | None = None,
        terminal: Terminal | None = None,
    ) -> None:
        self.state = InteractiveState(
            base_url=initial_base_url or os.getenv("SCAN_API_URL", DEFAULT_BASE_URL),
            timeout=initial_timeout,
            api_key=initial_api_key or os.getenv("SCAN_API_KEY"),
        )
        self.terminal = terminal or Terminal()

    def run(self) -> int:
        while True:
            self._render_home()
            choice = self.terminal.prompt("Выберите действие").strip().lower()

            if choice == "1":
                self.state.last_scan_id = self._scan_and_wait()
            elif choice == "2":
                self.state.last_scan_id = self._start_scan()
            elif choice == "3":
                self._download_report()
            elif choice == "4":
                self._settings()
            elif choice in {"5", "q", "quit", "exit"}:
                self.terminal.output(self.terminal.paint("Выход.", DIM))
                return 0
            else:
                self.terminal.notice("Неизвестный пункт меню.", kind="warn")
                self.terminal.pause()

    def _render_home(self) -> None:
        self.terminal.clear()
        self.terminal.hero()
        self.terminal.section("Подключение")
        self.terminal.output(f"  API:     {self.terminal.paint(self.state.base_url, BLUE)}")
        self.terminal.output(f"  Timeout: {self.terminal.paint(f'{self.state.timeout:g}s', BLUE)}")
        if self.state.api_key:
            self.terminal.output(f"  API key: {self.terminal.paint('задан', BLUE)}")
        else:
            self.terminal.output(
                "  API key: "
                + self.terminal.paint("не задан — запрошу при сканировании", DIM)
            )
        last_id_style = BLUE if self.state.last_scan_id else DIM
        self.terminal.output(f"  Last ID: {self.terminal.paint(self.state.last_scan_id or '-', last_id_style)}")

        self.terminal.section("Меню")
        self.terminal.menu_item("1", "Запустить скан и дождаться TXT-отчета")
        self.terminal.menu_item("2", "Только создать скан")
        self.terminal.menu_item("3", "Скачать готовый отчет")
        self.terminal.menu_item("4", "Настройки подключения")
        self.terminal.menu_item("5", "Выход")
        self.terminal.output("")

    def _scan_and_wait(self) -> str | None:
        repo_url = self.terminal.prompt("Ссылка на репозиторий").strip()
        if not repo_url:
            self.terminal.notice("Ссылка не указана.", kind="warn")
            self.terminal.pause()
            return None
        webhook_url = self._webhook_url()

        try:
            self.terminal.output("")
            self.terminal.output(self.terminal.paint("Запускаю скан...", BLUE))
            scan_id = self._call_with_auth_retry(
                lambda: self._client().start_scan(repo_url, webhook_url=webhook_url)
            )
            self.terminal.output(f"{self.terminal.paint('Скан создан:', GREEN)} {scan_id}")

            output_path = self._report_path(scan_id)
            interval = self.terminal.prompt_float("Интервал проверки, сек [2]", 2.0)
            wait_timeout = self.terminal.prompt_float(
                "Таймаут ожидания, сек [1800, 0 = бесконечно]", 1800.0
            )

            report = self._poll_report(
                self._client(),
                scan_id,
                interval=interval,
                timeout=None if wait_timeout == 0 else wait_timeout,
            )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
            self.terminal.notice(f"Отчет сохранен: {output_path}", kind="ok")
            self._show_report(report)
            self.terminal.pause()
            return scan_id
        except (ScanApiError, TimeoutError) as exc:
            self.terminal.notice(str(exc), kind="error")
            self.terminal.pause()
            return None

    def _start_scan(self) -> str | None:
        repo_url = self.terminal.prompt("Ссылка на репозиторий").strip()
        if not repo_url:
            self.terminal.notice("Ссылка не указана.", kind="warn")
            self.terminal.pause()
            return None
        webhook_url = self._webhook_url()

        try:
            scan_id = self._call_with_auth_retry(
                lambda: self._client().start_scan(repo_url, webhook_url=webhook_url)
            )
            self.terminal.notice(f"Скан создан: {scan_id}", kind="ok")
            self.terminal.pause()
            return scan_id
        except ScanApiError as exc:
            self.terminal.notice(str(exc), kind="error")
            self.terminal.pause()
            return None

    def _download_report(self) -> None:
        suffix = f" [{self.state.last_scan_id}]" if self.state.last_scan_id else ""
        scan_id = self.terminal.prompt(f"ID скана{suffix}").strip() or self.state.last_scan_id
        if not scan_id:
            self.terminal.notice("ID скана не указан.", kind="warn")
            self.terminal.pause()
            return

        output_path = self._report_path(scan_id)
        try:
            report = self._call_with_auth_retry(
                lambda: self._client().get_report(scan_id)
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")
            self.terminal.notice(f"Отчет сохранен: {output_path}", kind="ok")
            self._show_report(report)
        except ReportNotReady:
            self.terminal.notice(
                "Скан еще выполняется. Можно вернуться позже или выбрать полный сценарий ожидания.",
                kind="warn",
            )
        except ScanNotFound as exc:
            self.terminal.notice(f"Скан не найден: {exc}", kind="error")
        except ScanFailed as exc:
            self.terminal.notice(f"Скан завершился ошибкой: {exc}", kind="error")
        except ScanApiError as exc:
            self.terminal.notice(str(exc), kind="error")
        self.terminal.pause()

    def _settings(self) -> None:
        self.terminal.section("Настройки подключения")
        base_url = self.terminal.prompt(f"Base URL [{self.state.base_url}]").strip()
        if base_url:
            self.state.base_url = base_url
        self.state.timeout = self.terminal.prompt_float(
            f"HTTP timeout, сек [{self.state.timeout:g}]",
            self.state.timeout,
        )
        current_key = "задан" if self.state.api_key else "не задан"
        api_key = self.terminal.prompt(f"API key (Bearer) [{current_key}, Enter — без изменений]").strip()
        if api_key:
            self.state.api_key = api_key
        self.terminal.notice("Настройки обновлены для текущей сессии CLI.", kind="ok")
        self.terminal.pause()

    def _report_path(self, scan_id: str) -> Path:
        raw = self.terminal.prompt(f"Куда сохранить отчет [{default_report_path(scan_id)}]").strip()
        return Path(raw) if raw else default_report_path(scan_id)

    def _show_report(self, report: str) -> None:
        """Печатает markdown-отчёт в терминал в читаемом виде."""
        self.terminal.section("Отчёт")
        self.terminal.output(render_markdown(report, color=self.terminal.color))

    def _poll_report(
        self,
        client: ScanClient,
        scan_id: str,
        *,
        interval: float,
        timeout: float | None,
    ) -> str:
        started_at = time.monotonic()
        frames = ("◐", "◓", "◑", "◒") if self.terminal.color else ("-", "\\", "|", "/")
        attempt = 0

        while True:
            try:
                report = client.get_report(scan_id)
                self.terminal.output("")
                self.terminal.output(self.terminal.paint("Отчет готов. Скачиваю файл...", GREEN))
                return report
            except ReportNotReady:
                elapsed = time.monotonic() - started_at
                if timeout is not None and elapsed >= timeout:
                    raise TimeoutError(f"Отчет для скана {scan_id} не был готов за {timeout:g} сек.")

                frame = frames[attempt % len(frames)]
                attempt += 1
                self.terminal.output(
                    f"\r{self.terminal.paint(frame, MAGENTA)} "
                    f"Отчет еще готовится... прошло {elapsed:0.1f} сек",
                    end="",
                )
                time.sleep(interval)

    def _client(self) -> ScanClient:
        return ScanClient(
            base_url=self.state.base_url,
            timeout=self.state.timeout,
            api_key=self.state.api_key,
        )

    def _prompt_for_api_key(self) -> bool:
        """Запрашивает Bearer-ключ и сохраняет его в состоянии сессии.

        Возвращает True, если ключ введён, и False — если пользователь
        отменил ввод (пустая строка).
        """
        self.terminal.notice(
            "Бэкенду нужен API-ключ (Bearer). Для локального docker-стека "
            "это значение API_KEY из .env (по умолчанию changeme).",
            kind="warn",
        )
        key = self.terminal.prompt("API key (Enter — отмена)").strip()
        if key:
            self.state.api_key = key
            self.terminal.notice("Ключ сохранён для текущей сессии CLI.", kind="ok")
            return True
        return False

    def _call_with_auth_retry(self, action):
        """Выполняет вызов API; при ошибке авторизации (HTTP 401/403)
        запрашивает ключ и повторяет вызов.

        `action` обязан заново строить клиента (через `self._client()`),
        чтобы повтор подхватил обновлённый ключ.
        """
        while True:
            try:
                return action()
            except ScanAuthError as exc:
                self.terminal.notice(str(exc), kind="error")
                if not self._prompt_for_api_key():
                    raise

    def _webhook_url(self) -> str | None:
        raw = self.terminal.prompt("Webhook URL [optional]").strip()
        return raw or None
