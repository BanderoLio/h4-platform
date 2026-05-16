"""Агент-валидатор («скептик»).

Получает находки специалистов в evidence-only виде (без их severity и
confidence), независимо проверяет достижимость sink, режет false
positives и проставляет `status` + `cvss`. Это снижает confirmation
bias: валидатор не наследует уверенность специалиста.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from langgraph.prebuilt import create_react_agent

from ..config import CONFIG, elapsed
from ..llm import build_llm
from ..prompts import VALIDATOR_PROMPT
from ..schema import (
    STATUS_CONFIRMED,
    STATUS_FALSE_POSITIVE,
    STATUS_LIKELY,
    STATUS_UNVERIFIED,
    Finding,
)
from ..tools.filesystem import glob_files, grep, list_dir, read_file

_VALID_STATUS = {STATUS_CONFIRMED, STATUS_LIKELY, STATUS_FALSE_POSITIVE}


def _extract_json(text: str) -> dict:
    """Достаёт первый JSON-объект из ответа LLM.

    Модель часто оборачивает JSON в markdown-блок ```json``` или
    использует одинарные кавычки/висячие запятые — терпим всё это.
    """
    raw = text or ""
    # Снимаем markdown-ограждение, если есть.
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ValueError("в ответе валидатора нет JSON-объекта")
    blob = match.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Терпимый разбор: одинарные кавычки → двойные, срез висячих запятых.
        repaired = re.sub(r",(\s*[}\]])", r"\1", blob)
        if "'" in repaired and '"' not in repaired:
            repaired = repaired.replace("'", '"')
        return json.loads(repaired)


def _evidence_view(finding: Finding) -> str:
    """Формирует evidence-only описание находки — без severity/confidence
    специалиста, чтобы валидатор оценивал независимо."""
    return (
        f"Класс: {finding.vuln_class}\n"
        f"Заголовок: {finding.title}\n"
        f"CWE: {finding.cwe or 'не указан'}\n"
        f"Файл: {finding.file or 'не указан'}\n"
        f"Описание: {finding.description or '—'}\n"
        f"Поток данных: {finding.data_flow or '—'}\n"
        f"PoC: {finding.poc or '—'}\n\n"
        "Проверь находку по коду и верни JSON по своей инструкции."
    )


def make_validator_node():
    """Собирает узел графа `validate`: принимает state, возвращает
    `validated_findings`."""
    agent = create_react_agent(
        build_llm(),
        [read_file, list_dir, glob_files, grep],
        prompt=VALIDATOR_PROMPT,
    )
    # Лимит шагов ниже общего: проверка одной находки — это пара чтений
    # файлов и вывод, длинная петля здесь не нужна и опасна.
    run_cfg = {"recursion_limit": CONFIG.validator_recursion_limit}

    def _invoke_bounded(finding: Finding):
        """Гоняет ReAct-агента валидатора в daemon-потоке с таймаутом —
        одна зависшая проверка не должна держать весь узел `validate`."""
        box: dict = {}

        def _work() -> None:
            try:
                box["result"] = agent.invoke(
                    {"messages": [("user", _evidence_view(finding))]}, run_cfg)
            except Exception as err:  # noqa: BLE001
                box["error"] = err

        worker = threading.Thread(target=_work, daemon=True)
        worker.start()
        worker.join(CONFIG.validator_timeout_sec)
        if worker.is_alive():
            raise TimeoutError(
                f"проверка не уложилась в {CONFIG.validator_timeout_sec}с")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _validate_one(finding: Finding) -> Finding:
        t0 = time.perf_counter()
        try:
            result = _invoke_bounded(finding)
            verdict = _extract_json(result["messages"][-1].content)
        except Exception as err:  # noqa: BLE001 — сбой валидатора не роняет граф
            # Не смогли проверить — оставляем как unverified, фиксируем причину.
            dt = time.perf_counter() - t0
            print(f"[+{elapsed()}]   [валидатор] {finding.id or finding.title[:30]}"
                  f": не проверено за {dt:.0f}с ({str(err)[:80]})")
            finding.status = STATUS_UNVERIFIED
            finding.validation = {"error": str(err)[:300]}
            return finding
        status = str(verdict.get("status", "")).strip().lower()
        finding.status = status if status in _VALID_STATUS else STATUS_UNVERIFIED
        severity = str(verdict.get("severity", "")).strip().capitalize()
        if severity in {"Critical", "High", "Medium", "Low", "Info"}:
            finding.severity = severity
        try:
            finding.cvss = round(float(verdict.get("cvss")), 1)
        except (TypeError, ValueError):
            finding.cvss = None
        finding.validation = {
            "rationale": str(verdict.get("rationale", "")).strip(),
            "blind": True,
        }
        dt = time.perf_counter() - t0
        print(f"[+{elapsed()}]   [валидатор] {finding.id or finding.title[:30]}"
              f": {finding.status} за {dt:.0f}с")
        return finding

    def validate(state) -> dict:
        findings = state.get("findings", []) or []
        if not findings:
            return {"validated_findings": []}
        t0 = time.perf_counter()
        workers = max(1, min(CONFIG.validator_max_workers, len(findings)))
        print(f"[+{elapsed()}]   [валидатор] проверка {len(findings)} находок "
              f"(параллельно, потоков: {workers})")
        # Находки независимы — проверяем пулом потоков. Порядок сохраняем
        # через executor.map, чтобы нумерация F-NNN не перемешалась.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            validated = list(pool.map(_validate_one, findings))
        kept = [f for f in validated if f.status != STATUS_FALSE_POSITIVE]
        cut = len(validated) - len(kept)
        dt = time.perf_counter() - t0
        print(f"[+{elapsed()}]   [валидатор] готово за {dt:.0f}с: "
              f"подтверждено/вероятно — оставлено {len(kept)}, FP отсеяно — {cut}")
        return {"validated_findings": kept}

    return validate
