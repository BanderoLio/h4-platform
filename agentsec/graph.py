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

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents.specialists import SPECIALIST_LABELS, make_specialist_runners
from .agents.validator import make_validator_node
from .config import CONFIG, elapsed
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
    return "clarify" if state.get("needs_clarification") else "recon"


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

    explore_q = (
        f"Изучи репозиторий под задачу: {task}. Опиши структуру, языки и "
        "фреймворки, точки входа (HTTP-роуты, CLI, обработчики), ключевые "
        "файлы и attack surface."
    )
    try:
        parts.append("## Разведка кодовой базы\n" +
                      minions["explore_codebase"].invoke({"query": explore_q}))
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
        scope = state.get("scope") or {}
        focus = vuln_class in (scope.get("focus") or _FOCUS_CLASSES)
        clar = "\n".join(
            f"Q: {c['question']}\nA: {c['answer']}"
            for c in state.get("clarifications", [])
        )
        task = (
            f"Задача пользователя: {state['task']}\n\n"
            f"{state.get('recon', '')}\n\n"
            + (f"Уточнения пользователя:\n{clar}\n\n" if clar else "")
            + ("Этот класс уязвимостей в приоритете задачи.\n"
               if focus else "")
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
                    "coverage": [Coverage(area=vuln_class, status="done")],
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
    graph.add_conditional_edges(
        "intake", _route_after_intake,
        {"clarify": "clarify", "recon": "recon"},
    )
    graph.add_edge("clarify", "recon")
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
