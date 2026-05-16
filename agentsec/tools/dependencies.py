"""Dependency discovery and vulnerability lookup tools.

The functions are intentionally deterministic and usable both as LangChain
tools and as plain Python helpers from reports/eval code.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from ..config import CONFIG

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env"}


@dataclass
class Dependency:
    name: str
    version: str | None
    ecosystem: str
    source: str


def _root() -> Path:
    return CONFIG.analysis_root.resolve()


def _safe_rel(path: Path) -> str:
    return str(path.resolve().relative_to(_root()))


def _iter_manifest_files() -> list[Path]:
    names = {
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "go.mod",
    }
    files: list[Path] = []
    for path in _root().rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.name in names:
            files.append(path)
    return sorted(files)


def _parse_requirements(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*(?:==|>=|<=|~=|>|<)?\s*([^;, ]+)?", line)
        if match:
            deps.append(Dependency(match.group(1), match.group(2), "PyPI", _safe_rel(path)))
    return deps


def _parse_package_json(path: Path) -> list[Dependency]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    deps: list[Dependency] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, version in (data.get(section) or {}).items():
            deps.append(Dependency(str(name), str(version).lstrip("^~"), "npm", _safe_rel(path)))
    return deps


def _parse_package_lock(path: Path) -> list[Dependency]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    deps: list[Dependency] = []
    for name, meta in (data.get("dependencies") or {}).items():
        deps.append(Dependency(str(name), str((meta or {}).get("version") or ""), "npm", _safe_rel(path)))
    packages = data.get("packages") or {}
    for key, meta in packages.items():
        if not key.startswith("node_modules/"):
            continue
        name = key.removeprefix("node_modules/")
        deps.append(Dependency(name, str((meta or {}).get("version") or ""), "npm", _safe_rel(path)))
    return deps


def _parse_go_mod(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    in_block = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("//", 1)[0].strip()
        if line == "require (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            line = line.removeprefix("require ").strip()
        if in_block or raw.strip().startswith("require "):
            parts = line.split()
            if len(parts) >= 2:
                deps.append(Dependency(parts[0], parts[1], "Go", _safe_rel(path)))
    return deps


def resolve_dependencies_data() -> list[Dependency]:
    """Return dependencies from common manifest and lock files."""
    found: list[Dependency] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for path in _iter_manifest_files():
        if path.name == "requirements.txt":
            parsed = _parse_requirements(path)
        elif path.name == "package.json":
            parsed = _parse_package_json(path)
        elif path.name == "package-lock.json":
            parsed = _parse_package_lock(path)
        elif path.name == "go.mod":
            parsed = _parse_go_mod(path)
        else:
            parsed = []
        for dep in parsed:
            key = (dep.name.lower(), dep.version, dep.ecosystem, dep.source)
            if key not in seen:
                seen.add(key)
                found.append(dep)
    return found


@tool
def resolve_dependencies() -> str:
    """Parse dependency manifests and lock files in the analyzed repository."""
    deps = resolve_dependencies_data()
    if not deps:
        return "Зависимости не найдены: нет поддерживаемых manifest/lock-файлов."
    payload = [asdict(dep) for dep in deps]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _osv_query(dep: Dependency) -> dict[str, Any]:
    body: dict[str, Any] = {
        "package": {"name": dep.name, "ecosystem": dep.ecosystem},
    }
    if dep.version and dep.version not in {"*", "latest"}:
        clean_version = re.sub(r"^[~^<>= ]+", "", dep.version).strip()
        if clean_version:
            body["version"] = clean_version
    req = urllib.request.Request(
        "https://api.osv.dev/v1/query",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as response:  # noqa: S310 - fixed OSV URL
        return json.loads(response.read().decode("utf-8"))


@tool
def search_dependency_cves(limit: int = 25) -> str:
    """Query OSV for vulnerabilities in discovered dependencies."""
    deps = resolve_dependencies_data()[: max(1, min(limit, 100))]
    if not deps:
        return "Зависимости для CVE/OSV-поиска не найдены."
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for dep in deps:
        try:
            vulns = (_osv_query(dep).get("vulns") or [])[:10]
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
            errors.append(f"{dep.ecosystem}:{dep.name}: {err}")
            continue
        for vuln in vulns:
            results.append(
                {
                    "dependency": asdict(dep),
                    "id": vuln.get("id"),
                    "summary": vuln.get("summary"),
                    "aliases": vuln.get("aliases") or [],
                    "modified": vuln.get("modified"),
                }
            )
    payload = {"vulnerabilities": results, "errors": errors[:10]}
    return json.dumps(payload, ensure_ascii=False, indent=2)
