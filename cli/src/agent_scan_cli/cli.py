from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable

from . import __version__
from .client import DEFAULT_BASE_URL, ReportNotReady, ScanApiError, ScanClient, default_report_path

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CLEAR = "\033[2J\033[H"


def build_parser() -> argparse.ArgumentParser:
    connection_options = argparse.ArgumentParser(add_help=False)
    _add_connection_options(connection_options, suppress_defaults=True)

    parser = argparse.ArgumentParser(
        prog="agent-scan",
        description="Start repository scans and download TXT reports.",
    )
    _add_connection_options(parser)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser(
        "start",
        help="Start a repository scan.",
        parents=[connection_options],
    )
    start.add_argument("repo_url", help="Repository URL to scan.")

    report = subparsers.add_parser(
        "report",
        help="Download a finished scan report.",
        parents=[connection_options],
    )
    report.add_argument("scan_id", help="Scan id returned by the start command.")
    report.add_argument("-o", "--output", type=Path, help="Where to write the TXT report.")

    scan = subparsers.add_parser(
        "scan",
        help="Start a scan and wait until the TXT report is ready.",
        parents=[connection_options],
    )
    scan.add_argument("repo_url", help="Repository URL to scan.")
    scan.add_argument("-o", "--output", type=Path, help="Where to write the TXT report.")
    scan.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    scan.add_argument(
        "--wait-timeout",
        type=float,
        default=600.0,
        help="Maximum time to wait for the report in seconds. Use 0 to wait forever.",
    )

    return parser


def _add_connection_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else os.getenv("SCAN_API_URL", DEFAULT_BASE_URL)
    timeout_default = argparse.SUPPRESS if suppress_defaults else 30.0
    parser.add_argument(
        "--base-url",
        default=default,
        help=f"Scan API base URL. Defaults to SCAN_API_URL or {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=timeout_default,
        help="HTTP timeout in seconds.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        if sys.stdin.isatty():
            return run_interactive()
        parser.print_help()
        return 0

    args = parser.parse_args(argv)
    if args.command is None:
        if sys.stdin.isatty():
            return run_interactive(initial_base_url=args.base_url, initial_timeout=args.timeout)
        parser.print_help()
        return 0

    client = ScanClient(base_url=args.base_url, timeout=args.timeout)

    try:
        if args.command == "start":
            scan_id = client.start_scan(args.repo_url)
            print(scan_id)
            return 0

        if args.command == "report":
            output = args.output or default_report_path(args.scan_id)
            client.save_report(args.scan_id, output)
            print(f"Report saved: {output}")
            return 0

        if args.command == "scan":
            scan_id = client.start_scan(args.repo_url)
            print(f"Scan started: {scan_id}", file=sys.stderr)

            wait_timeout = None if args.wait_timeout == 0 else args.wait_timeout
            report = client.wait_for_report(
                scan_id,
                interval=args.interval,
                timeout=wait_timeout,
            )

            output = args.output or default_report_path(scan_id)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(report)
            print(f"Report saved: {output}")
            return 0

        raise AssertionError(f"Unknown command: {args.command}")
    except ReportNotReady:
        print("Report is not ready yet.", file=sys.stderr)
        return 4
    except TimeoutError as exc:
        print(f"Timed out: {exc}", file=sys.stderr)
        return 3
    except ScanApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


def run_interactive(
    *,
    initial_base_url: str | None = None,
    initial_timeout: float = 30.0,
    input_func: Callable[[str], str] = input,
    output: Callable[..., None] = print,
) -> int:
    color = _supports_color()
    base_url = initial_base_url or os.getenv("SCAN_API_URL", DEFAULT_BASE_URL)
    timeout = initial_timeout
    last_scan_id: str | None = None

    while True:
        _clear(output, color=color)
        _banner(output, color=color)
        _status_panel(output, base_url=base_url, timeout=timeout, last_scan_id=last_scan_id, color=color)
        _menu(output, color=color)

        choice = _prompt(input_func, "Выберите действие", color=color).strip()

        if choice == "1":
            client = ScanClient(base_url=base_url, timeout=timeout)
            last_scan_id = _interactive_scan(client, input_func=input_func, output=output, color=color)
        elif choice == "2":
            client = ScanClient(base_url=base_url, timeout=timeout)
            last_scan_id = _interactive_start(client, input_func=input_func, output=output, color=color)
        elif choice == "3":
            client = ScanClient(base_url=base_url, timeout=timeout)
            _interactive_report(client, input_func=input_func, output=output, color=color, default_scan_id=last_scan_id)
        elif choice == "4":
            base_url, timeout = _interactive_settings(
                input_func=input_func,
                output=output,
                color=color,
                base_url=base_url,
                timeout=timeout,
            )
        elif choice in {"5", "q", "quit", "exit"}:
            output(_paint("Выход.", DIM, color=color))
            return 0
        else:
            _notice(output, "Неизвестный пункт меню.", color=color, kind="warn")
            _pause(input_func, color=color)


def _interactive_scan(
    client: ScanClient,
    *,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
    color: bool,
) -> str | None:
    repo_url = _prompt(input_func, "Ссылка на репозиторий", color=color).strip()
    if not repo_url:
        _notice(output, "Ссылка не указана.", color=color, kind="warn")
        _pause(input_func, color=color)
        return None

    output("")
    try:
        output(_paint("Запускаю скан...", CYAN, color=color))
        scan_id = client.start_scan(repo_url)
        output(f"{_paint('Скан создан:', GREEN, color=color)} {scan_id}")

        output_path_raw = _prompt(
            input_func,
            f"Куда сохранить отчет [{default_report_path(scan_id)}]",
            color=color,
        ).strip()
        output_path = Path(output_path_raw) if output_path_raw else default_report_path(scan_id)

        interval = _prompt_float(input_func, "Интервал проверки, сек [2]", 2.0, color=color)
        wait_timeout = _prompt_float(input_func, "Таймаут ожидания, сек [600, 0 = бесконечно]", 600.0, color=color)
        report = _poll_report(
            client,
            scan_id,
            interval=interval,
            timeout=None if wait_timeout == 0 else wait_timeout,
            output=output,
            color=color,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(report)
        _notice(output, f"Отчет сохранен: {output_path}", color=color, kind="ok")
        _pause(input_func, color=color)
        return scan_id
    except (ScanApiError, TimeoutError) as exc:
        _notice(output, str(exc), color=color, kind="error")
        _pause(input_func, color=color)
        return None


def _interactive_start(
    client: ScanClient,
    *,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
    color: bool,
) -> str | None:
    repo_url = _prompt(input_func, "Ссылка на репозиторий", color=color).strip()
    if not repo_url:
        _notice(output, "Ссылка не указана.", color=color, kind="warn")
        _pause(input_func, color=color)
        return None

    try:
        scan_id = client.start_scan(repo_url)
        _notice(output, f"Скан создан: {scan_id}", color=color, kind="ok")
        _pause(input_func, color=color)
        return scan_id
    except ScanApiError as exc:
        _notice(output, str(exc), color=color, kind="error")
        _pause(input_func, color=color)
        return None


def _interactive_report(
    client: ScanClient,
    *,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
    color: bool,
    default_scan_id: str | None,
) -> None:
    suffix = f" [{default_scan_id}]" if default_scan_id else ""
    scan_id = _prompt(input_func, f"ID скана{suffix}", color=color).strip() or default_scan_id
    if not scan_id:
        _notice(output, "ID скана не указан.", color=color, kind="warn")
        _pause(input_func, color=color)
        return

    output_path_raw = _prompt(
        input_func,
        f"Куда сохранить отчет [{default_report_path(scan_id)}]",
        color=color,
    ).strip()
    output_path = Path(output_path_raw) if output_path_raw else default_report_path(scan_id)

    try:
        client.save_report(scan_id, output_path)
        _notice(output, f"Отчет сохранен: {output_path}", color=color, kind="ok")
    except ReportNotReady:
        _notice(output, "Отчет еще не готов. Можно вернуться позже или выбрать полный сценарий ожидания.", color=color, kind="warn")
    except ScanApiError as exc:
        _notice(output, str(exc), color=color, kind="error")
    _pause(input_func, color=color)


def _interactive_settings(
    *,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
    color: bool,
    base_url: str,
    timeout: float,
) -> tuple[str, float]:
    output("")
    output(_paint("Настройки подключения", BOLD + CYAN, color=color))

    new_base_url = _prompt(input_func, f"Base URL [{base_url}]", color=color).strip() or base_url
    new_timeout = _prompt_float(input_func, f"HTTP timeout, сек [{timeout:g}]", timeout, color=color)

    _notice(output, "Настройки обновлены для текущей сессии CLI.", color=color, kind="ok")
    _pause(input_func, color=color)
    return new_base_url, new_timeout


def _poll_report(
    client: ScanClient,
    scan_id: str,
    *,
    interval: float,
    timeout: float | None,
    output: Callable[..., None],
    color: bool,
) -> bytes:
    started_at = time.monotonic()
    frames = ("◐", "◓", "◑", "◒") if color else ("-", "\\", "|", "/")
    attempt = 0

    while True:
        try:
            report = client.get_report(scan_id)
            output("")
            output(_paint("Отчет готов. Скачиваю файл...", GREEN, color=color))
            return report
        except ReportNotReady:
            elapsed = time.monotonic() - started_at
            if timeout is not None and elapsed >= timeout:
                raise TimeoutError(f"Отчет для скана {scan_id} не был готов за {timeout:g} сек.")

            frame = frames[attempt % len(frames)]
            attempt += 1
            output(
                f"\r{_paint(frame, MAGENTA, color=color)} "
                f"Отчет еще готовится... прошло {elapsed:0.1f} сек",
                end="",
            )
            time.sleep(interval)


def _banner(output: Callable[..., None], *, color: bool) -> None:
    lines = [
        "┌──────────────────────────────────────────────┐",
        "│              AGENT SCAN CONSOLE              │",
        "│        репозиторий -> агент -> отчет         │",
        "└──────────────────────────────────────────────┘",
    ]
    for line in lines:
        output(_paint(line, CYAN + BOLD, color=color))


def _status_panel(
    output: Callable[..., None],
    *,
    base_url: str,
    timeout: float,
    last_scan_id: str | None,
    color: bool,
) -> None:
    output("")
    output(_paint("Подключение", BOLD, color=color))
    output(f"  API:     {_paint(base_url, BLUE, color=color)}")
    output(f"  Timeout: {_paint(f'{timeout:g}s', BLUE, color=color)}")
    output(f"  Last ID: {_paint(last_scan_id or '-', BLUE if last_scan_id else DIM, color=color)}")


def _menu(output: Callable[..., None], *, color: bool) -> None:
    output("")
    output(_paint("Меню", BOLD, color=color))
    output(f"  {_paint('1', GREEN, color=color)}  Запустить скан и дождаться TXT-отчета")
    output(f"  {_paint('2', GREEN, color=color)}  Только создать скан")
    output(f"  {_paint('3', GREEN, color=color)}  Скачать готовый отчет")
    output(f"  {_paint('4', GREEN, color=color)}  Настройки подключения")
    output(f"  {_paint('5', GREEN, color=color)}  Выход")
    output("")


def _prompt(input_func: Callable[[str], str], label: str, *, color: bool) -> str:
    return input_func(f"{_paint('›', CYAN + BOLD, color=color)} {label}: ")


def _prompt_float(input_func: Callable[[str], str], label: str, default: float, *, color: bool) -> float:
    while True:
        value = _prompt(input_func, label, color=color).strip()
        if not value:
            return default
        try:
            parsed = float(value)
        except ValueError:
            print(_paint("Введите число.", YELLOW, color=color))
            continue
        if parsed < 0:
            print(_paint("Значение не может быть меньше нуля.", YELLOW, color=color))
            continue
        return parsed


def _notice(output: Callable[..., None], message: str, *, color: bool, kind: str) -> None:
    palette = {
        "ok": (GREEN, "OK"),
        "warn": (YELLOW, "WAIT"),
        "error": (RED, "ERR"),
    }
    style, label = palette[kind]
    output("")
    output(f"{_paint(label, style + BOLD, color=color)}  {message}")


def _pause(input_func: Callable[[str], str], *, color: bool) -> None:
    input_func(_paint("\nНажмите Enter, чтобы вернуться в меню...", DIM, color=color))


def _clear(output: Callable[..., None], *, color: bool) -> None:
    if color:
        output(CLEAR, end="")


def _paint(text: str, style: str, *, color: bool) -> str:
    if not color:
        return text
    return f"{style}{text}{RESET}"


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


if __name__ == "__main__":
    raise SystemExit(main())
