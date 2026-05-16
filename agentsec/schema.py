"""Структурированная схема находки — общий контракт системы.

`Finding` используют специалисты (через парсер markdown), консолидация
(дедупликация), валидатор (status/CVSS) и отчётность (JSON/markdown).
Схема намеренно на dataclass-ах: без новых зависимостей, и `reporting`
уже умеет сериализовать dataclass.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Ранг severity — для сортировки находок и порогов quality gate.
SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Info": 0}

# Статус находки после валидации.
STATUS_CONFIRMED = "confirmed"
STATUS_LIKELY = "likely"
STATUS_FALSE_POSITIVE = "false_positive"
STATUS_UNVERIFIED = "unverified"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def severity_key(value: str) -> str:
    """Нормализует строку severity к каноничному ключу (Critical/High/…/Info)."""
    parts = (value or "").strip().split()
    return parts[0].capitalize() if parts else "Info"


@dataclass
class Finding:
    """Одна уязвимость. Поля совпадают с FINDING_FORMAT из prompts.py."""

    title: str
    severity: str = "Info"            # Critical / High / Medium / Low / Info
    confidence: str = "Speculative"   # Confirmed / Likely / Speculative
    status: str = STATUS_UNVERIFIED   # см. STATUS_* выше
    vuln_class: str = "unknown"       # injection / secrets / authnz
    cwe: str = ""
    cvss: float | None = None
    file: str = ""                    # path/to/file.ext:line
    description: str = ""
    data_flow: str = ""
    poc: str = ""
    recommendation: str = ""
    found_by: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    @property
    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(severity_key(self.severity), 0)

    def fingerprint(self) -> str:
        """Стабильный отпечаток для дедупликации.

        Считаем находки одинаковыми, если совпали класс CWE (или, при
        отсутствии CWE, заголовок) и файл без номера строки — две формы
        записи одной дыры от разных специалистов схлопываются в одну.
        """
        ident = _norm(self.cwe) or _norm(self.title)
        location = re.sub(r":\d+\s*$", "", _norm(self.file))
        return hashlib.sha1(f"{ident}|{location}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Соответствие меток markdown-формата полям Finding.
_FIELD_MAP = {
    "CWE": "cwe",
    "Severity": "severity",
    "Confidence": "confidence",
    "Файл": "file",
    "Описание": "description",
    "Поток данных": "data_flow",
    "PoC": "poc",
    "Рекомендация": "recommendation",
}


def parse_findings_markdown(
    markdown: str,
    *,
    vuln_class: str = "unknown",
    found_by: list[str] | None = None,
) -> list[Finding]:
    """Разбирает markdown-отчёт специалиста в список `Finding`.

    Ожидается FINDING_FORMAT из prompts.py. Это контракт A↔B на время,
    пока B не подключит `with_structured_output`; парсер изолирован, его
    легко заменить, не трогая граф.
    """
    findings: list[Finding] = []
    for block in re.split(r"\n(?=### \[)", markdown or ""):
        head = re.search(r"^### \[(?P<sev>[^\]]+)]\s*(?P<title>.+)$", block, re.M)
        if not head:
            continue
        finding = Finding(
            title=head.group("title").strip(),
            severity=head.group("sev").strip(),
            vuln_class=vuln_class,
            found_by=list(found_by or []),
        )
        for label, attr in _FIELD_MAP.items():
            match = re.search(rf"- \*\*{re.escape(label)}:\*\*\s*(.+)", block)
            if match:
                setattr(finding, attr, match.group(1).strip())
        findings.append(finding)
    return findings


def _merge_pair(base: Finding, other: Finding) -> Finding:
    """Сливает дубль в базовую находку: объединяет источники и оставляет
    более серьёзную оценку."""
    base.found_by = sorted(set(base.found_by) | set(other.found_by))
    if other.severity_rank > base.severity_rank:
        base.severity = other.severity
    # Берём непустые поля из дубля, если в базе их нет.
    for attr in ("cwe", "data_flow", "poc", "recommendation", "description"):
        if not getattr(base, attr) and getattr(other, attr):
            setattr(base, attr, getattr(other, attr))
    base.evidence = {**other.evidence, **base.evidence}
    return base


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """Схлопывает находки с одинаковым fingerprint, нумерует (F-001…) и
    сортирует по убыванию severity."""
    merged: dict[str, Finding] = {}
    for finding in findings:
        key = finding.fingerprint()
        if key in merged:
            _merge_pair(merged[key], finding)
        else:
            merged[key] = finding
    ordered = sorted(merged.values(), key=lambda f: f.severity_rank, reverse=True)
    for index, finding in enumerate(ordered, start=1):
        finding.id = f"F-{index:03d}"
    return ordered


@dataclass
class Coverage:
    """Отметка покрытия: что реально проанализировал узел графа."""

    area: str                  # класс уязвимостей или область разведки
    status: str = "done"       # done / partial / gap / error
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- quality gate -----------------------------------------------------------

VERDICT_PASS = "PASS"
VERDICT_REVIEW = "NEEDS_REVIEW"
VERDICT_FAIL = "FAIL"

# Exit-code для CI: FAIL блокирует сборку, REVIEW — мягкая блокировка.
VERDICT_EXIT_CODE = {VERDICT_PASS: 0, VERDICT_REVIEW: 2, VERDICT_FAIL: 1}


def compute_verdict(
    findings: list[Finding],
    *,
    fail_severities: tuple[str, ...] = ("Critical", "High"),
) -> dict[str, Any]:
    """Детерминированный вердикт quality gate по валидированным находкам.

    - FAIL  — есть подтверждённая/вероятная находка severity из стоп-листа;
    - NEEDS_REVIEW — такая находка есть, но ещё не подтверждена валидатором,
      либо есть непустые coverage-gaps (учитываются вызывающим);
    - PASS  — ничего блокирующего.
    """
    fail_set = set(fail_severities)
    blocking = [
        f for f in findings
        if severity_key(f.severity) in fail_set
        and f.status in (STATUS_CONFIRMED, STATUS_LIKELY)
    ]
    needs_review = [
        f for f in findings
        if severity_key(f.severity) in fail_set
        and f.status == STATUS_UNVERIFIED
    ]
    if blocking:
        verdict = VERDICT_FAIL
    elif needs_review:
        verdict = VERDICT_REVIEW
    else:
        verdict = VERDICT_PASS
    counts: dict[str, int] = {}
    for finding in findings:
        key = severity_key(finding.severity)
        counts[key] = counts.get(key, 0) + 1
    return {
        "verdict": verdict,
        "blocking": [f.id for f in blocking],
        "needs_review": [f.id for f in needs_review],
        "severity_counts": counts,
        "total_findings": len(findings),
    }
