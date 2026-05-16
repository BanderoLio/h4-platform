"""Детерминистические сканеры как источник кандидатов триажа.

semgrep с курируемыми security-правилами даёт настоящие кандидаты с
dataflow — точнее, чем наша regex-эвристика sink-ов. Сканер гоняется по
файлам-кандидатам Repo Map (не по всему репо), поэтому быстр даже на
большом репозитории.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# Ключевые слова в semgrep check_id → класс уязвимостей.
_CLASS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "secrets": ("secret", "hardcoded", "credential", "crypto", "jwt",
                "password", "md5", "sha1", "cipher", "weak-"),
    "authnz": ("auth", "access-control", "csrf", "authz", "permission",
               "idor", "session", "open-redirect"),
    "injection": ("sql", "injection", "xss", "ssrf", "command", "eval",
                  "deserial", "tainted", "traversal", "xxe", "ldap"),
}


def classify_rule(check_id: str) -> str:
    """Сопоставляет правило сканера классу специалиста по ключевым словам."""
    cid = (check_id or "").lower()
    for vuln_class, keywords in _CLASS_KEYWORDS.items():
        if any(kw in cid for kw in keywords):
            return vuln_class
    return "injection"  # дефолт: большинство security-правил semgrep


def semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def run_semgrep(repo_root: Path, files: list[str], *,
                timeout: int = 240, max_files: int = 1200) -> list[dict]:
    """Гоняет semgrep по списку файлов, возвращает находки как кандидаты.

    Пустой список / отсутствие semgrep / сбой → пустой результат
    (пайплайн продолжает на regex-кандидатах).
    """
    exe = shutil.which("semgrep")
    if not exe or not files:
        return []
    targets = files[:max_files]
    cmd = [exe, "scan", "--config", "auto", "--json", "--quiet",
           "--metrics", "off", "--timeout", "10", *targets]
    try:
        result = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (subprocess.SubprocessError, OSError):
        return []
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []

    findings: list[dict] = []
    for res in data.get("results", []):
        check_id = res.get("check_id", "")
        extra = res.get("extra") or {}
        findings.append({
            "tool": "semgrep",
            "rule": check_id,
            "vuln_class": classify_rule(check_id),
            "file": res.get("path", ""),
            "line": (res.get("start") or {}).get("line", 0) or 0,
            "severity": str(extra.get("severity", "INFO")),
            "message": str(extra.get("message", ""))[:300],
        })
    return findings
