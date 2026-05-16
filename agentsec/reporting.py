"""Report persistence helpers for markdown, JSON, and optional HTML."""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return cleaned or "agentsec-report"


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    if is_dataclass(finding):
        return asdict(finding)
    if hasattr(finding, "model_dump"):
        return finding.model_dump()
    if isinstance(finding, dict):
        return dict(finding)
    return {"raw": str(finding)}


def _markdown_to_finding_dicts(markdown: str) -> list[dict[str, Any]]:
    """Best-effort parser for the MVP markdown format.

    B's structured Finding schema can replace this path later; keeping the
    parser here lets reporting work before that dependency lands.
    """
    findings: list[dict[str, Any]] = []
    blocks = re.split(r"\n(?=### \[)", markdown)
    for block in blocks:
        title = re.search(r"^### \[(?P<severity>[^\]]+)]\s*(?P<title>.+)$", block, re.M)
        if not title:
            continue
        item: dict[str, Any] = {
            "title": title.group("title").strip(),
            "severity": title.group("severity").strip(),
        }
        for key in ("CWE", "Severity", "Confidence", "Файл", "Описание", "Поток данных", "PoC", "Рекомендация"):
            match = re.search(rf"- \*\*{re.escape(key)}:\*\*\s*(.+)", block)
            if match:
                item[key] = match.group(1).strip()
        findings.append(item)
    return findings


def findings_to_jsonable(findings: list[Any] | None = None, markdown: str | None = None) -> list[dict[str, Any]]:
    if findings is not None:
        return [_finding_to_dict(finding) for finding in findings]
    if markdown:
        return _markdown_to_finding_dicts(markdown)
    return []


def _render_finding(finding: Any) -> str:
    """Рендерит один Finding в markdown-блок FINDING_FORMAT."""
    d = _finding_to_dict(finding)
    ident = d.get("id") or ""
    title = d.get("title", "находка")
    severity = d.get("severity", "Info")
    lines = [f"### [{severity}] {(ident + ' ') if ident else ''}{title}"]
    status = d.get("status")
    cvss = d.get("cvss")
    pairs = [
        ("CWE", d.get("cwe")),
        ("Severity", severity),
        ("Confidence", d.get("confidence")),
        ("Status", status),
        ("CVSS", cvss),
        ("Файл", d.get("file")),
        ("Найдено", ", ".join(d.get("found_by", []) or []) or None),
        ("Описание", d.get("description")),
        ("Поток данных", d.get("data_flow")),
        ("PoC", d.get("poc")),
        ("Рекомендация", d.get("recommendation")),
    ]
    for key, value in pairs:
        if value not in (None, "", []):
            lines.append(f"- **{key}:** {value}")
    rationale = (d.get("validation") or {}).get("rationale")
    if rationale:
        lines.append(f"- **Вердикт валидатора:** {rationale}")
    return "\n".join(lines)


def render_report(
    *,
    findings: list[Any],
    verdict: dict[str, Any] | None = None,
    coverage: list[Any] | None = None,
    task: str = "",
    repo: str = "",
) -> str:
    """Собирает итоговый markdown-отчёт из структурных находок, вердикта
    quality gate и трекинга покрытия."""
    verdict = verdict or {}
    counts = verdict.get("severity_counts", {})
    summary_counts = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "нет"
    lines = [
        "# Отчёт анализа безопасности",
        "",
        f"**Задача:** {task or '—'}  ",
        f"**Репозиторий:** {repo or '—'}",
        "",
        "## Quality gate",
        "",
        f"- **Вердикт:** {verdict.get('verdict', 'N/A')}",
        f"- **Находок всего:** {verdict.get('total_findings', len(findings))}",
        f"- **По severity:** {summary_counts}",
        f"- **Блокирующих:** {', '.join(verdict.get('blocking', [])) or 'нет'}",
    ]
    if verdict.get("user_decision"):
        lines.append(f"- **Решение пользователя:** {verdict['user_decision']}")
    lines.append("")
    lines.append("## Находки")
    lines.append("")
    if findings:
        for finding in findings:
            lines.append(_render_finding(finding))
            lines.append("")
    else:
        lines.append("Уязвимости не подтверждены.")
        lines.append("")
    lines.append("## Покрытие")
    lines.append("")
    if coverage:
        for item in coverage:
            d = _finding_to_dict(item)
            note = f" — {d['note']}" if d.get("note") else ""
            lines.append(f"- `{d.get('area', '?')}`: {d.get('status', '?')}{note}")
    else:
        lines.append("- данные о покрытии отсутствуют")
    gaps = verdict.get("coverage_gaps") or []
    if gaps:
        lines.append("")
        lines.append("**Непокрытые области требуют ручной проверки.**")
    lines.append("")
    return "\n".join(lines)


def _html_report(markdown: str, payload: dict[str, Any]) -> str:
    body = html.escape(markdown).replace("\n", "<br>\n")
    meta = html.escape(json.dumps(payload.get("metadata", {}), ensure_ascii=False, indent=2))
    return (
        "<!doctype html>\n"
        "<html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<title>agentsec report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:980px;margin:40px auto;"
        "line-height:1.5;color:#1f2937}pre{background:#f3f4f6;padding:16px;overflow:auto}"
        "code{background:#f3f4f6;padding:2px 4px}</style></head><body>"
        "<h1>agentsec report</h1>"
        f"<pre>{meta}</pre><main>{body}</main></body></html>\n"
    )


def save_report(
    *,
    markdown: str,
    findings: list[Any] | None = None,
    output_dir: str | Path = "reports",
    formats: list[str] | None = None,
    task: str = "",
    repo: str | Path | None = None,
    scanner_outputs: dict[str, str] | None = None,
    verdict: dict[str, Any] | None = None,
    coverage: list[Any] | None = None,
) -> dict[str, Path]:
    """Save a report in requested formats and return generated paths."""
    selected = {fmt.lower() for fmt in (formats or ["md", "json"])}
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = _slug(f"{Path(repo).name if repo else 'repo'}-{stamp}")
    paths: dict[str, Path] = {}
    jsonable_findings = findings_to_jsonable(findings, markdown)
    payload = {
        "metadata": {
            "task": task,
            "repo": str(repo) if repo else None,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "formats": sorted(selected),
        },
        "verdict": verdict or {},
        "findings": jsonable_findings,
        "coverage": [_finding_to_dict(c) for c in (coverage or [])],
        "scanner_outputs": scanner_outputs or {},
        "markdown": markdown,
    }
    if "md" in selected or "markdown" in selected:
        path = out_dir / f"{base}.md"
        path.write_text(markdown, encoding="utf-8")
        paths["markdown"] = path
    if "json" in selected:
        path = out_dir / f"{base}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["json"] = path
    if "html" in selected:
        path = out_dir / f"{base}.html"
        path.write_text(_html_report(markdown, payload), encoding="utf-8")
        paths["html"] = path
    return paths
