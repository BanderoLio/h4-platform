"""Tiny regression harness for comparing generated reports with expectations."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _contains_all(report: str, terms: list[str]) -> bool:
    lower = report.lower()
    return all(term.lower() in lower for term in terms)


def score_report(report: str, expected_path: Path) -> dict[str, object]:
    spec = json.loads(expected_path.read_text(encoding="utf-8"))
    checks = []
    passed = 0
    for check in spec["checks"]:
        ok = _contains_all(report, check["must_match"])
        passed += int(ok)
        checks.append({"id": check["id"], "passed": ok, "must_match": check["must_match"]})
    return {"passed": passed, "total": len(checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an agentsec report against expected findings.")
    parser.add_argument("--report", help="Existing markdown/text report to score")
    parser.add_argument("--expected", default="eval/expected/vulnerable_app.json")
    parser.add_argument("--run", action="store_true", help="Run main.py on the target before scoring")
    parser.add_argument("--task", default="Проведи аудит безопасности")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    expected = (repo_root / args.expected).resolve()
    if args.run:
        spec = json.loads(expected.read_text(encoding="utf-8"))
        target = repo_root / spec["target"]
        proc = subprocess.run(
            [sys.executable, str(repo_root / "main.py"), "--repo", str(target), "--task", args.task],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        report = proc.stdout + "\n" + proc.stderr
    elif args.report:
        report = Path(args.report).read_text(encoding="utf-8")
    else:
        parser.error("pass --report or --run")

    result = score_report(report, expected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
