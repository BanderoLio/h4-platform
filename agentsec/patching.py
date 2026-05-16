"""Генерация candidate-патчей по подтверждённым находкам."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import CONFIG
from .schema import STATUS_FALSE_POSITIVE

_PATCH_PROMPT = """\
Ты — security remediation assistant. Тебе дают структурированную находку и
фрагмент кода. Предложи МИНИМАЛЬНЫЙ и реалистичный патч, который исправляет
уязвимость, не меняя бизнес-логику сверх необходимого.

Верни СТРОГО JSON-объект без обрамления:
- "summary": 1-2 предложения, почему патч устраняет проблему;
- "target_file": путь к файлу, который правится;
- "unified_diff": diff в unified формате (`---`, `+++`, `@@`), применимый к
  target_file. Если контекста недостаточно — пустая строка;
- "confidence": high | medium | low.

Ограничения:
- Патч должен менять только один файл;
- Не выдумывай новые пути;
- Если данных мало — не фантазируй, оставь unified_diff пустым и объясни это
  в summary.
"""


def _value(finding: Any, key: str, default: Any = "") -> Any:
    if isinstance(finding, dict):
        return finding.get(key, default)
    return getattr(finding, key, default)


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _strip_fences(text: str) -> str:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    return clean.strip()


def _normalize_diff(text: str) -> str:
    clean = _strip_fences(text).replace("\r\n", "\n").strip()
    if not clean:
        return ""
    if not re.search(r"^---\s.+", clean, re.M) or not re.search(r"^\+\+\+\s.+", clean, re.M):
        return ""
    if not clean.endswith("\n"):
        clean += "\n"
    return clean


def _parse_file_ref(file_ref: str) -> tuple[str, int | None]:
    raw = re.sub(r"[\u2010-\u2015]", "-", (file_ref or "").strip())
    raw = raw.replace("`", "")
    if not raw:
        return "", None
    if ":" not in raw:
        return raw, None
    maybe_path, maybe_line = raw.rsplit(":", 1)
    range_match = re.match(r"^\s*(\d+)(?:\s*-\s*\d+)?\s*$", maybe_line)
    if range_match:
        return maybe_path.strip(), int(range_match.group(1))
    return raw, None


def _extract_file_candidates(file_ref: str) -> list[tuple[str, int | None]]:
    text = re.sub(r"[\u2010-\u2015]", "-", (file_ref or ""))
    text = text.replace("`", "")
    candidates: list[tuple[str, int | None]] = []
    seen: set[tuple[str, int | None]] = set()
    pattern = re.compile(
        r"(?P<path>[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)"
        r"(?::\s*(?P<line>\d+)(?:\s*-\s*\d+)?)?"
    )
    for match in pattern.finditer(text):
        path = match.group("path")
        if not path:
            continue
        line_str = match.group("line")
        line = int(line_str) if line_str else None
        key = (path, line)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(key)
    if candidates:
        return candidates
    fallback = _parse_file_ref(file_ref)
    return [fallback] if fallback[0] else []


def _resolve_target(root: Path, rel: str) -> tuple[str | None, Path | None, str | None]:
    target = Path(rel).expanduser()
    if not target.is_absolute():
        target = (root / target).resolve()
    else:
        target = target.resolve()
    try:
        rel_path = str(target.relative_to(root))
    except ValueError:
        return None, None, "файл вне корня анализируемого репозитория"
    return rel_path, target, None


def _read_context(root: Path, file_ref: str) -> tuple[str | None, str | None, str | None]:
    candidates = _extract_file_candidates(file_ref)
    if not candidates:
        return None, None, "в находке не указан путь к файлу"
    first_rel = candidates[0][0]
    outside_root = False
    for rel, line_no in candidates:
        rel_path, target, resolve_error = _resolve_target(root, rel)
        if resolve_error:
            outside_root = True
            continue
        if target is None or rel_path is None:
            continue
        if not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            return rel_path, None, f"ошибка чтения файла: {err}"

        lines = content.splitlines()
        if not lines:
            return rel_path, "", None

        radius = CONFIG.patch_context_radius
        if line_no is not None and line_no > 0:
            start = max(1, line_no - radius)
            end = min(len(lines), line_no + radius)
        else:
            start = 1
            end = min(len(lines), radius * 2 + 1)

        chunk = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
        return rel_path, "\n".join(chunk), None
    if outside_root:
        return first_rel, None, "файл вне корня анализируемого репозитория"
    return first_rel, None, "файл не найден в репозитории"


def _build_patch_request(finding: Any, rel_path: str, snippet: str) -> str:
    payload = {
        "finding": {
            "id": _value(finding, "id"),
            "title": _value(finding, "title"),
            "severity": _value(finding, "severity"),
            "status": _value(finding, "status"),
            "cwe": _value(finding, "cwe"),
            "description": _value(finding, "description"),
            "data_flow": _value(finding, "data_flow"),
            "recommendation": _value(finding, "recommendation"),
            "file_ref": _value(finding, "file"),
        },
        "target_file": rel_path,
        "code_context": snippet,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _candidate_findings(findings: list[Any]) -> list[Any]:
    accepted = []
    for item in findings:
        if _value(item, "status") != STATUS_FALSE_POSITIVE:
            accepted.append(item)
    return accepted


def generate_fix_patches(*, findings: list[Any], repo: str | Path) -> list[dict[str, Any]]:
    """Генерирует candidate-patch (unified diff) для подтверждённых находок."""
    if not findings:
        return []
    candidates = _candidate_findings(findings)
    if not candidates:
        return []
    # Ленивый импорт: сохранение отчётов и unit-тесты не должны требовать
    # установленных LLM-зависимостей, если patch-генерация не вызывается.
    from .llm import build_llm

    root = Path(repo).expanduser().resolve() if repo else CONFIG.analysis_root.resolve()
    llm = build_llm(temperature=0.0)
    patches: list[dict[str, Any]] = []

    for finding in candidates[: CONFIG.patch_max_findings]:
        file_ref = str(_value(finding, "file", "") or "")
        rel_path, snippet, context_error = _read_context(root, file_ref)
        entry = {
            "finding_id": str(_value(finding, "id", "") or ""),
            "title": str(_value(finding, "title", "") or ""),
            "severity": str(_value(finding, "severity", "") or ""),
            "status": str(_value(finding, "status", "") or ""),
            "file": file_ref,
            "target_file": rel_path or "",
            "summary": "",
            "confidence": "",
            "unified_diff": "",
            "error": "",
        }
        if context_error:
            entry["summary"] = (
                str(_value(finding, "recommendation", "") or "")
                or "Недостаточно контекста для автоматического diff-патча."
            )
            entry["error"] = context_error
            patches.append(entry)
            continue

        request = _build_patch_request(finding, rel_path or "", snippet or "")
        try:
            reply = llm.invoke([("system", _PATCH_PROMPT), ("user", request)])
            parsed = _extract_json(getattr(reply, "content", str(reply)))
        except Exception as err:  # noqa: BLE001 — провайдер может отвалиться
            entry["summary"] = (
                str(_value(finding, "recommendation", "") or "")
                or "Не удалось сгенерировать патч из-за ошибки LLM."
            )
            entry["error"] = str(err)[:180]
            patches.append(entry)
            continue

        entry["summary"] = str(
            parsed.get("summary")
            or _value(finding, "recommendation", "")
            or "Candidate-патч для устранения находки."
        ).strip()
        entry["confidence"] = str(parsed.get("confidence", "") or "").strip()
        target_file = str(parsed.get("target_file", "") or rel_path or "").strip()
        if target_file:
            entry["target_file"] = target_file
        entry["unified_diff"] = _normalize_diff(str(parsed.get("unified_diff", "") or ""))
        if not entry["unified_diff"] and not entry["error"]:
            entry["error"] = "модель не вернула применимый unified diff"
        patches.append(entry)
    return patches


def render_fix_patches_markdown(patches: list[dict[str, Any]]) -> str:
    """Рендерит markdown-документ с candidate-патчами."""
    lines = ["# Кандидатные патчи", ""]
    if not patches:
        lines.append("Патчи не сгенерированы.")
        lines.append("")
        return "\n".join(lines)

    for patch in patches:
        title = patch.get("title") or "Найденная проблема"
        fid = patch.get("finding_id") or "F-???"
        lines.append(f"## {fid} {title}".strip())
        lines.append("")
        lines.append(f"- **Файл:** {patch.get('target_file') or patch.get('file') or '—'}")
        lines.append(f"- **Severity:** {patch.get('severity') or '—'}")
        lines.append(f"- **Статус:** {patch.get('status') or '—'}")
        lines.append(f"- **Обоснование:** {patch.get('summary') or '—'}")
        if patch.get("confidence"):
            lines.append(f"- **Confidence патча:** {patch['confidence']}")
        if patch.get("error"):
            lines.append(f"- **Ограничение:** {patch['error']}")
        lines.append("")
        diff = (patch.get("unified_diff") or "").strip()
        if diff:
            lines.append("```diff")
            lines.append(diff)
            lines.append("```")
        else:
            lines.append("_Unified diff отсутствует._")
        lines.append("")
    return "\n".join(lines)


def render_fix_patches_diff(patches: list[dict[str, Any]]) -> str:
    """Собирает единый .diff-бандл из всех сгенерированных патчей."""
    blocks: list[str] = []
    for patch in patches:
        diff = (patch.get("unified_diff") or "").strip()
        if not diff:
            continue
        title = patch.get("title") or "finding"
        fid = patch.get("finding_id") or "F-???"
        blocks.append(f"# {fid}: {title}")
        blocks.append(diff)
        blocks.append("")
    if not blocks:
        return ""
    joined = "\n".join(blocks).rstrip()
    return joined + "\n"
