"""Тесты Repo Map: построение индекса, инкрементальность, запросы, инструменты."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentsec.config import CONFIG
from agentsec.index import index_repo
from agentsec.index import query as Q
from agentsec.index.builder import build_repo_map
from agentsec.index.languages import language_of, role_of

_APP_PY = '''\
import sqlite3, subprocess

API_KEY = "sk-secret"

def get_user(uid):
    db = sqlite3.connect("x")
    return db.execute("SELECT * FROM u WHERE id=" + uid)

@app.route("/ping")
def ping():
    host = request.args.get("host")
    return subprocess.check_output("ping " + host, shell=True)
'''

_UTILS_JS = '''\
function helper(x) { return doThing(x); }
const run = () => helper(1);
'''


def _make_repo(tmp: str) -> Path:
    root = Path(tmp)
    (root / "app.py").write_text(_APP_PY, encoding="utf-8")
    (root / "utils.js").write_text(_UTILS_JS, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_x(): pass\n",
                                                encoding="utf-8")
    return root


class BuildTest(unittest.TestCase):
    def test_build_extracts_symbols_entrypoints_sinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            rm = build_repo_map(_make_repo(tmp))
            names = {s.name for s in rm.symbols}
            self.assertIn("get_user", names)       # python ast
            self.assertIn("ping", names)
            self.assertIn("helper", names)         # js regex
            kinds = {e.name for e in rm.entry_points}
            self.assertIn("/ping", kinds)          # flask route
            sink_kinds = {s.kind for s in rm.sinks}
            self.assertIn("sql", sink_kinds)
            self.assertIn("command", sink_kinds)
            # граф вызовов: ping -> subprocess.check_output
            self.assertTrue(any(c.callee.endswith("check_output")
                                for c in rm.calls))

    def test_role_and_language_detection(self):
        self.assertEqual(language_of("a/b.py"), "python")
        self.assertEqual(language_of("a/b.ts"), "typescript")
        self.assertEqual(language_of("a/b.bin"), "unknown")
        self.assertEqual(role_of("tests/test_app.py"), "test")
        self.assertEqual(role_of("src/app.py"), "source")
        self.assertEqual(role_of("config.yaml"), "config")


class IncrementalTest(unittest.TestCase):
    def test_incremental_reuses_unchanged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(tmp)
            # БД по умолчанию — в .agentsec/ цели, этот каталог не обходится.
            store, st1 = index_repo(root)
            store.close()
            self.assertGreaterEqual(st1["indexed"], 3)
            self.assertEqual(st1["reused"], 0)

            # Повторный прогон без изменений — всё переиспользовано.
            store, st2 = index_repo(root)
            store.close()
            self.assertEqual(st2["indexed"], 0)
            self.assertGreaterEqual(st2["reused"], 3)

            # Меняем один файл — переиндексируется только он.
            (root / "app.py").write_text("def changed(): pass\n",
                                         encoding="utf-8")
            store, st3 = index_repo(root)
            store.close()
            self.assertEqual(st3["indexed"], 1)
            self.assertGreaterEqual(st3["reused"], 2)


class QueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = _make_repo(self._tmp.name)
        self.store, _ = index_repo(root)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_entry_points_and_filter(self):
        all_eps = Q.entry_points(self.store)
        self.assertTrue(any(e["name"] == "/ping" for e in all_eps))
        routes = Q.entry_points(self.store, kind="http_route")
        self.assertTrue(all(e["kind"] == "http_route" for e in routes))

    def test_sinks_filter_by_kind(self):
        sql = Q.sinks(self.store, kind="sql")
        self.assertTrue(sql and all(s["kind"] == "sql" for s in sql))

    def test_who_calls_matches_dotted(self):
        rows = Q.who_calls(self.store, "check_output")
        self.assertTrue(any("check_output" in r["callee"] for r in rows))

    def test_symbol_lookup_and_outline(self):
        self.assertTrue(Q.symbol_lookup(self.store, "get_user"))
        outline = Q.file_outline(self.store, "app.py")
        self.assertTrue(any(s["name"] == "ping" for s in outline))


class RepoMapToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = _make_repo(self._tmp.name)
        self._saved_root = CONFIG.analysis_root
        CONFIG.analysis_root = self._root
        # Индекс кладётся в .agentsec/index.db цели — туда же смотрят инструменты.
        index_repo(self._root)[0].close()

    def tearDown(self) -> None:
        CONFIG.analysis_root = self._saved_root
        self._tmp.cleanup()

    def test_tools_return_index_data(self):
        from agentsec.tools.repomap import (
            find_entry_points,
            find_sinks,
            repo_overview,
            who_calls,
        )
        self.assertIn("Точек входа", repo_overview.invoke({}))
        self.assertIn("/ping", find_entry_points.invoke({}))
        self.assertIn("sql", find_sinks.invoke({"kind": "sql"}))
        self.assertIn("check_output", who_calls.invoke({"name": "check_output"}))


class ReadFileWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_root = CONFIG.analysis_root
        CONFIG.analysis_root = Path(self._tmp.name)
        (Path(self._tmp.name) / "big.txt").write_text(
            "\n".join(f"line{i}" for i in range(1, 101)), encoding="utf-8")

    def tearDown(self) -> None:
        CONFIG.analysis_root = self._saved_root
        self._tmp.cleanup()

    def test_offset_limit_window(self):
        from agentsec.tools.filesystem import read_file
        out = read_file.invoke({"path": "big.txt", "offset": 10, "limit": 5})
        self.assertIn("строки 10-14 из 100", out)
        self.assertIn("10\tline10", out)
        self.assertIn("14\tline14", out)
        self.assertNotIn("line15", out)


if __name__ == "__main__":
    unittest.main()
