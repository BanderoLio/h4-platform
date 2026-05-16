"""Детерминированный StateGraph оркестрации анализа.

LLM решает, ЧТО найдено; граф решает, ЧТО запускается. Управление
потоком фиксировано — специалисты не пропускаются, в отличие от прежнего
ReAct-оркестратора, где модель сама выбирала, кого вызвать.

    START → intake → (clarify?) → recon ─┬─→ specialist_injection ─┐
                                         ├─→ specialist_secrets   ─┤
                                         └─→ specialist_authnz    ─┘
                                                                   │
                              consolidate ←──────────────────────┘
                                   │
                              validate → gate → report → END
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents.specialists import SPECIALIST_LABELS, make_specialist_runners
from .agents.triage import triage_specialist
from .agents.validator import make_validator_node
from .config import CONFIG, elapsed
from .index import index_repo
from .index import query as Q
from .index.model import (
    SINK_COMMAND,
    SINK_CRYPTO,
    SINK_DESERIALIZE,
    SINK_EVAL,
    SINK_FILE,
    SINK_SQL,
    SINK_SSRF,
)
from .index.store import IndexStore, index_db_path
from .llm import build_llm
from .prompts import INTAKE_PROMPT
from .reporting import render_report
from .schema import (
    VERDICT_PASS,
    VERDICT_REVIEW,
    Coverage,
    compute_verdict,
    deduplicate,
    parse_findings_markdown,
)
from .state import AnalysisState
from .tools.interaction import ask_user

_FOCUS_CLASSES = ("injection", "secrets", "authnz")


def _log(msg: str) -> None:
    print(f"[+{elapsed()}]   {msg}")


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(match.group(0)) if match else {}


# --- узлы графа -------------------------------------------------------------

def _intake(state: AnalysisState) -> dict:
    """Интерпретирует задачу на естественном языке, решает про уточнение."""
    task = state["task"]
    _log(f"[intake] разбор задачи: {task[:120]}")
    scope: dict = {"focus": list(_FOCUS_CLASSES), "scope_summary": task}
    needs = False
    question = ""
    try:
        reply = build_llm().invoke(
            [("system", INTAKE_PROMPT), ("user", task)]
        )
        parsed = _extract_json(reply.content)
        focus = [c for c in parsed.get("focus", []) if c in _FOCUS_CLASSES]
        scope = {
            "focus": focus or list(_FOCUS_CLASSES),
            "scope_summary": str(parsed.get("scope_summary", task)).strip() or task,
        }
        needs = bool(parsed.get("needs_clarification")) and CONFIG.interactive
        question = str(parsed.get("clarifying_question", "")).strip()
    except Exception as err:  # noqa: BLE001 — intake не должен ронять прогон
        _log(f"[intake] не удалось разобрать ({err}); беру все классы")
    return {
        "scope": scope,
        "needs_clarification": needs and bool(question),
        "clarifying_question": question,
        "clarifications": [],
    }


def _route_after_intake(state: AnalysisState) -> str:
    return "clarify" if state.get("needs_clarification") else "index"


def _index(state: AnalysisState) -> dict:
    """Строит Repo Map — детерминированный индекс кодовой базы.

    Индекс (символы, граф вызовов, точки входа, sink-и) кэшируется в
    `.agentsec/index.db` цели и переиндексируется инкрементально. Это
    «контекст по репозиторию»: специалисты запрашивают карту вместо
    слепого обхода. Сбой индексации не роняет граф — анализ продолжится
    на grep-инструментах.
    """
    try:
        store, stats = index_repo(Path(CONFIG.analysis_root))
        summary = Q.summary(store)
        _log(f"[index] Repo Map: {summary['files']} файлов, "
             f"{summary['symbols']} символов, "
             f"{summary['entry_points']} точек входа, "
             f"{summary['sinks']} sink-ов "
             f"(переиндексировано {stats['indexed']}, "
             f"переиспользовано {stats['reused']})")
        _run_scanner_ingest(store, summary.get("commit", ""))
        store.close()
        return {"repo_map_summary": summary}
    except Exception as err:  # noqa: BLE001 — индексация не критична для прогона
        _log(f"[index] индексация не удалась: {err}")
        return {"repo_map_summary": {}}


def _run_scanner_ingest(store, commit: str) -> None:
    """Прогоняет semgrep по файлам-кандидатам и кладёт находки в индекс.

    Это источник ТОЧНЫХ кандидатов триажа (в отличие от regex-эвристики).
    Кэш по git-commit: повторный прогон того же коммита не пересканирует.
    Сбой/отсутствие semgrep — пайплайн продолжает на regex-кандидатах.
    """
    if not CONFIG.index_scanners:
        return
    from .index.scan import run_semgrep, semgrep_available

    if not semgrep_available():
        _log("[index] semgrep не установлен — кандидаты только из Repo Map")
        return
    if commit and store.get_meta("scanner_commit") == commit \
            and store.query("SELECT 1 FROM scanner_findings LIMIT 1"):
        _log("[index] находки сканеров взяты из кэша (commit не изменился)")
        return
    targets = store.candidate_files()
    _log(f"[index] semgrep по {len(targets)} файлам-кандидатам "
         f"(лимит {CONFIG.scanner_timeout_sec}с)")
    findings = run_semgrep(Path(CONFIG.analysis_root), targets,
                           timeout=CONFIG.scanner_timeout_sec)
    store.replace_scanner_findings(findings)
    store.set_meta(scanner_commit=commit or "")
    _log(f"[index] semgrep: {len(findings)} находок-кандидатов")


# Какие виды sink-ов и нужны ли точки входа каждому классу специалистов.
_CLASS_SINK_KINDS: dict[str, tuple[str, ...]] = {
    "injection": (SINK_SQL, SINK_COMMAND, SINK_EVAL, SINK_SSRF,
                  SINK_DESERIALIZE, SINK_FILE),
    "secrets": (SINK_CRYPTO,),
    "authnz": (),
}
_CLASS_USES_ENTRYPOINTS = {"injection", "authnz"}


def _repo_map_section() -> str:
    """Краткий обзор Repo Map для recon: масштаб и счётчики attack surface.

    Детальные списки не разворачиваем — их несёт пер-классовый бриф
    кандидатов в задаче специалиста (экономия контекста)."""
    path = index_db_path(Path(CONFIG.analysis_root))
    if not path.exists():
        return ""
    store = IndexStore(path)
    try:
        s = Q.summary(store)
    finally:
        store.close()
    return (
        "## Repo Map (индекс кодовой базы)\n"
        f"Файлов: {s['files']}, языки: {s['languages']}, "
        f"символов: {s['symbols']}.\n"
        f"Attack surface: {s['entry_points']} точек входа, "
        f"{s['sinks']} sink-ов по видам {s['sink_kinds']}.\n"
        "Детали — инструментами repo_overview / find_entry_points / "
        "find_sinks / find_symbol / who_calls / file_symbols."
    )


def _candidate_brief(vuln_class: str) -> tuple[str, int]:
    """Список кандidatов класса из Repo Map для триажа специалистом.

    Возвращает (текст брифа, всего кандидатов). Список обрезается бюджетом
    `max_candidates_per_specialist` — остаток явно помечается непокрытым.
    """
    path = index_db_path(Path(CONFIG.analysis_root))
    if not path.exists():
        return "", 0
    store = IndexStore(path)
    try:
        items: list[str] = []
        for kind in _CLASS_SINK_KINDS.get(vuln_class, ()):
            for s in Q.sinks(store, kind=kind):
                items.append(f"  {s['file']}:{s['line']} [sink:{s['kind']}] "
                             f"{s['snippet']}")
        if vuln_class in _CLASS_USES_ENTRYPOINTS:
            for e in Q.entry_points(store):
                items.append(f"  {e['file']}:{e['line']} [entry:{e['kind']}] "
                             f"{e['name']} {e['detail']}".rstrip())
    finally:
        store.close()

    total = len(items)
    if total == 0:
        return "", 0
    cap = CONFIG.max_candidates_per_specialist
    lines = [f"## Кандидаты для триажа из Repo Map — всего {total}"]
    lines += items[:cap]
    if total > cap:
        lines.append(f"  ... ещё {total - cap} кандидатов вне бюджета "
                     f"({cap}) — добери через find_sinks / find_entry_points")
    lines.append(
        "Триаж: по КАЖДОМУ кандидату проверь достижимость недоверенного "
        "ввода и подтверди уязвимость либо отклони (ложное срабатывание). "
        "Затем добери то, что индекс мог пропустить.")
    return "\n".join(lines), total


def _clarify(state: AnalysisState) -> dict:
    """Задаёт уточняющий вопрос пользователю (только в интерактиве).

    В server-режиме граф ставится на паузу через `interrupt()`: ответ
    приходит позже HTTP-запросом и возобновляет прогон. В CLI-режиме —
    привычный синхронный запрос в stdin.
    """
    question = state.get("clarifying_question") or "Уточните скоуп анализа."
    if CONFIG.server_mode:
        # Узел при возобновлении выполняется заново целиком; кода с
        # побочными эффектами до interrupt() здесь нет — это безопасно.
        answer = interrupt({"type": "clarify", "question": question})
    else:
        answer = ask_user.invoke({"question": question})
    return {"clarifications": [{"question": question, "answer": answer}]}


def _recon(state: AnalysisState) -> dict:
    """Детерминированная разведка: миньоны explore/docs + опционально сканеры."""
    from .agents.minions import make_minion_tools

    minions = {tool.name: tool for tool in make_minion_tools()}
    task = state["task"]
    _log("[recon] разведка кодовой базы")
    parts: list[str] = []
    coverage: list[Coverage] = []

    # Repo Map идёт первым: специалисты получают карту attack surface
    # ещё до свободной разведки миньонов.
    repo_section = _repo_map_section()
    if repo_section:
        parts.append(repo_section)

    # На большом репо explore-миньон (ReAct-агент) избыточен и медленен —
    # Repo Map уже даёт структуру/attack surface детерминированно. Гоняем
    # explore только на небольших репозиториях.
    files = (state.get("repo_map_summary") or {}).get("files", 0)
    if files and files > CONFIG.explore_skip_files:
        _log(f"[recon] большой репо ({files} файлов) — explore-миньон "
             "пропущен, используется Repo Map")
        coverage.append(Coverage(area="recon:codebase", status="done",
                                 note="Repo Map (explore-миньон пропущен)"))
    else:
        explore_q = (
            f"Изучи репозиторий под задачу: {task}. Опиши структуру, языки и "
            "фреймворки, точки входа (HTTP-роуты, CLI, обработчики), ключевые "
            "файлы и attack surface."
        )
        try:
            parts.append("## Разведка кодовой базы\n" +
                          minions["explore_codebase"].invoke(
                              {"query": explore_q}))
            coverage.append(Coverage(area="recon:codebase", status="done"))
        except Exception as err:  # noqa: BLE001
            coverage.append(Coverage(area="recon:codebase", status="error",
                                     note=str(err)[:200]))

    try:
        parts.append("## Документация и модель безопасности\n" +
                      minions["read_docs"].invoke(
                          {"query": "Назначение проекта, запуск, заявленная "
                                    "модель безопасности."}))
        coverage.append(Coverage(area="recon:docs", status="done"))
    except Exception as err:  # noqa: BLE001
        coverage.append(Coverage(area="recon:docs", status="error",
                                 note=str(err)[:200]))

    scanner_outputs: dict[str, str] = {}
    if CONFIG.run_scanners:
        from .tools.scanners import run_selected_scanners

        _log("[recon] запуск детерминистических сканеров")
        scanner_outputs = run_selected_scanners()
        for name, output in scanner_outputs.items():
            parts.append(f"## Сканер: {name}\n{output[:4000]}")
        coverage.append(Coverage(area="recon:scanners", status="done"))

    return {
        "recon": "\n\n".join(parts),
        "scanner_outputs": scanner_outputs,
        "coverage": coverage,
    }


def _make_specialist_node(vuln_class: str, runner):
    """Фабрика узла-специалиста: запуск с ретраями, парсинг markdown→Finding."""
    label = SPECIALIST_LABELS[vuln_class]

    def _node(state: AnalysisState) -> dict:
        if CONFIG.stub_specialists:
            return {"coverage": [Coverage(area=vuln_class, status="gap",
                                          note="стаб-режим")]}
        clar = "\n".join(
            f"Q: {c['question']}\nA: {c['answer']}"
            for c in state.get("clarifications", [])
        )
        # Triage-режим: если Repo Map построен — детерминированный триаж
        # кандидатов (инкрементально, с бюджетом; частичный результат
        # сохраняется при исчерпании времени).
        if index_db_path(Path(CONFIG.analysis_root)).exists():
            task_text = state["task"] + (
                f"\n\nУточнения пользователя:\n{clar}" if clar else "")
            try:
                return triage_specialist(vuln_class, task_text)
            except Exception as err:  # noqa: BLE001 — сбой триажа не роняет граф
                _log(f"[{label}] триаж упал: {err}")
                return {
                    "coverage": [Coverage(area=vuln_class, status="error",
                                          note=str(err)[:200])],
                    "errors": [f"триаж {label}: {err}"],
                }

        # Fallback: индекса нет (маленький репо/индексация не удалась) —
        # exploratory ReAct-специалист.
        scope = state.get("scope") or {}
        focus = vuln_class in (scope.get("focus") or _FOCUS_CLASSES)
        brief, n_candidates = _candidate_brief(vuln_class)
        task = (
            f"Задача пользователя: {state['task']}\n\n"
            f"{state.get('recon', '')}\n\n"
            + (f"Уточнения пользователя:\n{clar}\n\n" if clar else "")
            + ("Этот класс уязвимостей в приоритете задачи.\n"
               if focus else "")
            + (f"{brief}\n\n" if brief else "")
            + "Проверь репозиторий на свой класс уязвимостей и верни "
              "markdown-отчёт строго по FINDING_FORMAT."
        )
        last_err = ""
        for attempt in range(1, CONFIG.specialist_retries + 2):
            try:
                markdown = runner(task)
            except TimeoutError as err:
                # Ретрай по таймауту лишь сожжёт ещё один лимит времени —
                # сразу фиксируем пробел покрытия.
                last_err = str(err)[:200]
                break
            except Exception as err:  # noqa: BLE001
                last_err = str(err)[:200]
                continue
            findings = parse_findings_markdown(
                markdown, vuln_class=vuln_class, found_by=[vuln_class])
            if findings or "не найден" in markdown.lower():
                # Непустой результат ИЛИ явное «ничего не найдено» — успех.
                for f in findings:
                    f.evidence.setdefault("specialist_report", markdown[:2000])
                return {
                    "raw_findings": findings,
                    "coverage": [Coverage(
                        area=vuln_class, status="done",
                        note=f"кандидатов из Repo Map: {n_candidates}, "
                             f"находок: {len(findings)}")],
                }
            last_err = f"пустой отчёт ({len(markdown)} симв.)"
            _log(f"[{label}] попытка {attempt}: {last_err}, ретрай")
        # Все попытки исчерпаны — фиксируем пробел покрытия, граф не падает.
        _log(f"[{label}] пробел покрытия: {last_err}")
        return {
            "coverage": [Coverage(area=vuln_class, status="gap", note=last_err)],
            "errors": [f"специалист {label}: {last_err}"],
        }

    return _node


def _consolidate(state: AnalysisState) -> dict:
    """Дедуплицирует находки специалистов и нумерует их."""
    raw = state.get("raw_findings", []) or []
    findings = deduplicate(raw)
    _log(f"[consolidate] {len(raw)} находок → {len(findings)} после дедупликации")
    return {"findings": findings}


def _gate(state: AnalysisState) -> dict:
    """Quality gate: вердикт по порогам severity + решение пользователя."""
    findings = state.get("validated_findings", []) or []
    verdict = compute_verdict(
        findings, fail_severities=CONFIG.gate_fail_severities)
    gaps = [c for c in state.get("coverage", [])
            if c.status in ("gap", "error", "partial")]
    # Незакрытое покрытие не даёт чистого PASS — поднимаем до REVIEW.
    if gaps and verdict["verdict"] == VERDICT_PASS:
        verdict["verdict"] = VERDICT_REVIEW
    verdict["coverage_gaps"] = [c.to_dict() for c in gaps]
    _log(f"[gate] вердикт: {verdict['verdict']} "
         f"(находок: {verdict['total_findings']}, пробелов: {len(gaps)})")

    if CONFIG.interactive:
        prompt = (
            f"Рекомендация quality gate: {verdict['verdict']}. "
            f"Найдено блокирующих: {len(verdict['blocking'])}. "
            "Отдавать проект на сборку? (да / нет / комментарий)"
        )
        if CONFIG.server_mode:
            # compute_verdict выше — чистая и дешёвая функция; при
            # возобновлении узел пересчитает её повторно, это безопасно.
            answer = interrupt(
                {"type": "gate", "question": prompt, "verdict": verdict})
        else:
            answer = ask_user.invoke({"question": prompt})
        verdict["user_decision"] = answer
        verdict["approved_for_build"] = answer.strip().lower().startswith(
            ("да", "yes", "y"))
    else:
        verdict["user_decision"] = "(неинтерактивный режим)"
        verdict["approved_for_build"] = verdict["verdict"] == VERDICT_PASS
    return {"verdict": verdict}


def _report(state: AnalysisState) -> dict:
    """Рендерит итоговый markdown-отчёт."""
    report = render_report(
        findings=state.get("validated_findings", []) or [],
        verdict=state.get("verdict", {}),
        coverage=state.get("coverage", []),
        task=state.get("task", ""),
        repo=state.get("repo", ""),
        repo_map=state.get("repo_map_summary") or {},
    )
    return {"report_md": report}


# --- сборка графа ------------------------------------------------------------

def build_graph(checkpointer=None):
    """Собирает и компилирует StateGraph оркестратора.

    `checkpointer` (LangGraph saver) включает персистентность состояния:
    нужен для паузы на `interrupt()` и возобновления сессии. При
    `checkpointer=None` поведение идентично компиляции без аргументов —
    это CLI-путь.
    """
    runners = (
        {c: (lambda _t: "") for c in _FOCUS_CLASSES}
        if CONFIG.stub_specialists
        else make_specialist_runners()
    )
    graph = StateGraph(AnalysisState)

    graph.add_node("intake", _intake)
    graph.add_node("clarify", _clarify)
    graph.add_node("index", _index)
    graph.add_node("recon", _recon)
    for vuln_class in _FOCUS_CLASSES:
        graph.add_node(
            f"specialist_{vuln_class}",
            _make_specialist_node(vuln_class, runners[vuln_class]),
        )
    graph.add_node("consolidate", _consolidate)
    graph.add_node("validate", make_validator_node())
    graph.add_node("gate", _gate)
    graph.add_node("report", _report)

    graph.add_edge(START, "intake")
    # intake → index напрямую, либо через clarify (уточнение скоупа).
    graph.add_conditional_edges(
        "intake", _route_after_intake,
        {"clarify": "clarify", "index": "index"},
    )
    graph.add_edge("clarify", "index")
    # index строит Repo Map до разведки — recon и специалисты его используют.
    graph.add_edge("index", "recon")
    # recon → три специалиста параллельно (общий superstep)…
    for vuln_class in _FOCUS_CLASSES:
        graph.add_edge("recon", f"specialist_{vuln_class}")
        # …и сходятся на consolidate (узел ждёт все ветки).
        graph.add_edge(f"specialist_{vuln_class}", "consolidate")
    graph.add_edge("consolidate", "validate")
    graph.add_edge("validate", "gate")
    graph.add_edge("gate", "report")
    graph.add_edge("report", END)

    return graph.compile(checkpointer=checkpointer)
