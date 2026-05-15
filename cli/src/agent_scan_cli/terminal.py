from __future__ import annotations

import os
import sys
from typing import Callable

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
WHITE = "\033[37m"
CLEAR = "\033[2J\033[H"

PrintFn = Callable[..., None]
InputFn = Callable[[str], str]

HERO = [
    " ██████╗ ██╗ ██████╗  █████╗ ",
    "██╔════╝ ██║██╔════╝ ██╔══██╗",
    "██║  ███╗██║██║  ███╗███████║",
    "██║   ██║██║██║   ██║██╔══██║",
    "╚██████╔╝██║╚██████╔╝██║  ██║",
    " ╚═════╝ ╚═╝ ╚═════╝ ╚═╝  ╚═╝",
    "██████╗ ███████╗ █████╗ ██╗   ██╗███████╗██████╗ ",
    "██╔══██╗██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗",
    "██████╔╝█████╗  ███████║██║   ██║█████╗  ██████╔╝",
    "██╔══██╗██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝  ██╔══██╗",
    "██████╔╝███████╗██║  ██║ ╚████╔╝ ███████╗██║  ██║",
    "╚═════╝ ╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝",
]


class Terminal:
    def __init__(
        self,
        *,
        input_func: InputFn = input,
        output: PrintFn = print,
        color: bool | None = None,
    ) -> None:
        self.input = input_func
        self.output = output
        self.color = supports_color() if color is None else color

    def clear(self) -> None:
        if self.color:
            self.output(CLEAR, end="")

    def hero(self) -> None:
        for index, line in enumerate(HERO):
            style = CYAN + BOLD if index < 6 else MAGENTA + BOLD
            self.output(self.paint(line, style))
        self.output(self.paint("        repo intelligence console", DIM + WHITE))

    def section(self, title: str) -> None:
        self.output("")
        self.output(self.paint(title, BOLD))

    def menu_item(self, number: str, label: str) -> None:
        self.output(f"  {self.paint(number, GREEN + BOLD)}  {label}")

    def prompt(self, label: str) -> str:
        return self.input(f"{self.paint('›', CYAN + BOLD)} {label}: ")

    def prompt_float(self, label: str, default: float) -> float:
        while True:
            value = self.prompt(label).strip()
            if not value:
                return default
            try:
                parsed = float(value)
            except ValueError:
                self.output(self.paint("Введите число.", YELLOW))
                continue
            if parsed < 0:
                self.output(self.paint("Значение не может быть меньше нуля.", YELLOW))
                continue
            return parsed

    def notice(self, message: str, *, kind: str) -> None:
        palette = {
            "ok": (GREEN, "OK"),
            "warn": (YELLOW, "WAIT"),
            "error": (RED, "ERR"),
        }
        style, label = palette[kind]
        self.output("")
        self.output(f"{self.paint(label, style + BOLD)}  {message}")

    def pause(self) -> None:
        self.input(self.paint("\nНажмите Enter, чтобы вернуться в меню...", DIM))

    def paint(self, text: str, style: str) -> str:
        if not self.color:
            return text
        return f"{style}{text}{RESET}"


def supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None
