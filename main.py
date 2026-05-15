"""CLI-точка входа мультиагентной системы анализа кода на уязвимости.

Пример:
    python main.py --repo ./examples/vulnerable_app --task "Найди уязвимости"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Мультиагентный анализ кода на уязвимости (пентест).",
    )
    parser.add_argument("--repo", required=True, help="Путь к анализируемому репозиторию")
    parser.add_argument("--task", help="Задача оркестратору (если не задана — спросим)")
    parser.add_argument(
        "--yes", action="store_true",
        help="Авто-подтверждение записи файлов (без интерактивного запроса)",
    )
    args = parser.parse_args()

    # CONFIG импортируем и мутируем ДО импорта агентов и сборки LLM.
    from agentsec.config import CONFIG, elapsed

    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        print(f"ОШИБКА: каталог не найден: {root}")
        return 1
    CONFIG.analysis_root = root
    CONFIG.auto_approve_writes = args.yes

    task = args.task or input("Опишите задачу анализа: ").strip()
    if not task:
        print("Пустая задача — нечего анализировать.")
        return 1

    from agentsec.agents.orchestrator import run

    print(f"\n=== Анализ репозитория: {root} ===\n")
    CONFIG.started_at = time.monotonic()  # отсчёт времени с начала анализа
    report = run(task)

    print("\n" + "=" * 72)
    print(f"ИТОГОВЫЙ ОТЧЁТ  (время анализа: {elapsed()})")
    print("=" * 72)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
