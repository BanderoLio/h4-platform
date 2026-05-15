"""Wrappers for deterministic security scanners.

These wrappers do not require the scanners to be installed. Missing binaries
produce explicit coverage messages instead of failing the whole analysis.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from ..config import CONFIG


def _run_json_tool(command: list[str], timeout: int = 180) -> str:
    executable = shutil.which(command[0])
    if not executable:
        return json.dumps(
            {
                "status": "unavailable",
                "tool": command[0],
                "message": f"CLI '{command[0]}' is not installed or not on PATH.",
            },
            ensure_ascii=False,
            indent=2,
        )
    cmd = [executable, *command[1:]]
    try:
        result = subprocess.run(
            cmd,
            cwd=CONFIG.analysis_root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "timeout", "tool": command[0]}, ensure_ascii=False, indent=2)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {"raw_stdout": stdout}
    return json.dumps(
        {
            "status": "ok" if result.returncode in {0, 1} else "error",
            "tool": command[0],
            "returncode": result.returncode,
            "result": parsed,
            "stderr": stderr[-4000:],
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def run_semgrep(config: str = "auto") -> str:
    """Run semgrep against the analyzed repository and return JSON output."""
    return _run_json_tool(["semgrep", "scan", "--config", config, "--json", "."], timeout=240)


@tool
def run_gitleaks() -> str:
    """Run gitleaks secret detection against the analyzed repository."""
    root = Path(CONFIG.analysis_root)
    return _run_json_tool(
        ["gitleaks", "detect", "--source", str(root), "--no-git", "--report-format", "json"],
        timeout=180,
    )


@tool
def run_osv_scanner() -> str:
    """Run osv-scanner against dependency manifests in the analyzed repository."""
    return _run_json_tool(["osv-scanner", "--format", "json", "-r", "."], timeout=180)


def run_selected_scanners(names: list[str] | None = None) -> dict[str, str]:
    """Plain Python helper for CLI-driven scanner execution."""
    selected = set(names or ["semgrep", "gitleaks", "osv"])
    outputs: dict[str, str] = {}
    if "semgrep" in selected:
        outputs["semgrep"] = run_semgrep.invoke({"config": "auto"})
    if "gitleaks" in selected:
        outputs["gitleaks"] = run_gitleaks.invoke({})
    if "osv" in selected or "osv-scanner" in selected:
        outputs["osv-scanner"] = run_osv_scanner.invoke({})
    return outputs
