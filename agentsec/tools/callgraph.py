"""Coarse static callgraph extraction for common project types."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from langchain_core.tools import tool

from ..config import CONFIG

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env"}
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}


def _iter_code_files(limit: int) -> list[Path]:
    root = CONFIG.analysis_root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= limit:
            break
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _CODE_SUFFIXES:
            files.append(path)
    return files


def _python_calls(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    rel = str(path.resolve().relative_to(CONFIG.analysis_root.resolve()))
    out: list[dict[str, object]] = []
    scope = "<module>"
    parents: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parents.append(node.name)
            scope = ".".join(parents)
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = _call_name(child.func)
                    if name:
                        out.append({"file": rel, "caller": scope, "callee": name, "line": child.lineno})
            parents.pop()
    if not out:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name:
                    out.append({"file": rel, "caller": "<module>", "callee": name, "line": node.lineno})
    return out


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _js_calls(path: Path) -> list[dict[str, object]]:
    rel = str(path.resolve().relative_to(CONFIG.analysis_root.resolve()))
    out: list[dict[str, object]] = []
    func_rx = re.compile(r"\b(?:function\s+([A-Za-z_$][\w$]*)|([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)")
    call_rx = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")
    caller = "<module>"
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        func = func_rx.search(line)
        if func:
            caller = func.group(1) or func.group(2) or caller
        for match in call_rx.finditer(line):
            callee = match.group(1)
            if callee not in {"if", "for", "while", "switch", "function"}:
                out.append({"file": rel, "caller": caller, "callee": callee, "line": line_no})
    return out


@tool
def build_callgraph(max_files: int = 150, max_edges: int = 500) -> str:
    """Build a coarse static callgraph for Python/JS/TS files.

    This is deliberately approximate: it helps agents find likely sources,
    sinks, and dispatch paths before manual validation.
    """
    edges: list[dict[str, object]] = []
    errors: list[str] = []
    for path in _iter_code_files(max(1, min(max_files, 1000))):
        if len(edges) >= max_edges:
            break
        try:
            if path.suffix == ".py":
                edges.extend(_python_calls(path))
            else:
                edges.extend(_js_calls(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as err:
            errors.append(f"{path}: {err}")
    payload = {"edges": edges[:max_edges], "errors": errors[:20]}
    return json.dumps(payload, ensure_ascii=False, indent=2)
