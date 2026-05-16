"""CLI-точка входа мультиагентной системы анализа кода на уязвимости.

Пример:
    python main.py --repo ./examples/vulnerable_app --task "Найди уязвимости"

Код возврата используется как quality gate в CI:
    0 — сборку можно продолжать;
    1 — найдено блокирующее / сборка не одобрена;
    2 — требуется ручная проверка.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # CLI help and env-only setups should still work.
    def load_dotenv() -> bool:
        return False


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
    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Не задавать вопросов пользователю: intake и gate решают автоматически",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Каталог для сохранения отчётов (по умолчанию: reports)",
    )
    parser.add_argument(
        "--format",
        action="append",
        choices=["md", "json", "html"],
        help="Формат сохраняемого отчёта. Можно повторять: --format md --format json",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Не сохранять отчёт в файл, только вывести в stdout",
    )
    parser.add_argument(
        "--run-scanners",
        action="store_true",
        help="В фазе recon запустить semgrep/gitleaks/osv-scanner, если установлены",
    )
    parser.add_argument(
        "--no-patches",
        action="store_true",
        help="Отключить генерацию candidate-патчей после отчёта",
    )
    parser.add_argument(
        "--patch-max",
        type=int,
        help="Максимум находок для генерации candidate-патчей (по умолчанию из CONFIG)",
    )
    args = parser.parse_args()

    # CONFIG импортируем и мутируем ДО импорта агентов и сборки графа.
    from agentsec.config import CONFIG, elapsed

    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        print(f"ОШИБКА: каталог не найден: {root}")
        return 1
    CONFIG.analysis_root = root
    CONFIG.auto_approve_writes = args.yes
    CONFIG.run_scanners = args.run_scanners
    CONFIG.interactive = not args.non_interactive and sys.stdin.isatty()
    CONFIG.generate_fix_patches = not args.no_patches
    if args.patch_max is not None:
        if args.patch_max <= 0:
            print("ОШИБКА: --patch-max должен быть положительным числом.")
            return 1
        CONFIG.patch_max_findings = args.patch_max

    if args.task:
        task = args.task.strip()
    elif CONFIG.interactive:
        task = input("Опишите задачу анализа: ").strip()
    else:
        print("ОШИБКА: в неинтерактивном режиме задайте --task.")
        return 1
    if not task:
        print("Пустая задача — нечего анализировать.")
        return 1

    from agentsec.agents.orchestrator import run_analysis
    from agentsec.schema import VERDICT_EXIT_CODE, VERDICT_FAIL

    print(f"\n=== Анализ репозитория: {root} ===\n")
    CONFIG.started_at = time.monotonic()  # отсчёт времени с начала анализа

    state = run_analysis(task)
    report = state.get("report_md", "")
    verdict = state.get("verdict", {}) or {}
    patches = state.get("fix_patches", []) or []

    print("\n" + "=" * 72)
    print(f"ИТОГОВЫЙ ОТЧЁТ  (время анализа: {elapsed()})")
    print("=" * 72)
    print(report)
    if patches:
        with_diff = sum(1 for p in patches if p.get("unified_diff"))
        print(f"\nКандидатные патчи: {len(patches)} (с diff: {with_diff})")

    if not args.no_save:
        from agentsec.reporting import save_report

        paths = save_report(
            markdown=report,
            findings=state.get("validated_findings", []),
            output_dir=args.output_dir,
            formats=args.format or ["md", "json"],
            task=task,
            repo=root,
            scanner_outputs=state.get("scanner_outputs", {}),
            verdict=verdict,
            coverage=state.get("coverage", []),
            fix_patches=patches,
        )
        print("\nСохранённые отчёты:")
        for kind, path in paths.items():
            print(f"- {kind}: {path}")

    decision = verdict.get("verdict", VERDICT_FAIL)
    approved = verdict.get("approved_for_build", False)
    print(f"\nQuality gate: {decision} "
          f"(сборка {'одобрена' if approved else 'не одобрена'})")
    # CI-блокировка: одобренная пользователем сборка всегда даёт 0,
    # иначе — код по вердикту (FAIL=1, NEEDS_REVIEW=2).
    return 0 if approved else VERDICT_EXIT_CODE.get(decision, 1)


if __name__ == "__main__":
    sys.exit(main())
