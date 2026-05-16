"""Эвристики attack surface: точки входа и опасные операции (sinks).

Детект построчно по регулярным выражениям — дёшево, мультиязычно,
детерминированно. Это не замена semgrep, а быстрый слой триажа: даёт
агентам список «куда смотреть», не требуя LLM-обхода репозитория.
"""
from __future__ import annotations

import re

from .model import (
    EP_CLI,
    EP_HANDLER,
    EP_HTTP_ROUTE,
    EP_MAIN,
    SINK_COMMAND,
    SINK_CRYPTO,
    SINK_DESERIALIZE,
    SINK_EVAL,
    SINK_FILE,
    SINK_SECRET,
    SINK_SQL,
    SINK_SSRF,
    EntryPoint,
    Sink,
)

# --- sink-паттерны: (вид, скомпилированное regex) ---------------------------
_SINK_RX: list[tuple[str, re.Pattern]] = [
    (SINK_SQL, re.compile(r"\.execute(?:many|script)?\s*\(|\.raw\s*\(|"
                          r"\bdb\.query\s*\(|sequelize\.query\s*\(")),
    (SINK_COMMAND, re.compile(r"\bsubprocess\.|\bos\.system\s*\(|\bos\.popen|"
                              r"child_process|\.exec(?:Sync)?\s*\(|"
                              r"Runtime\.getRuntime|\bpopen\s*\(")),
    (SINK_DESERIALIZE, re.compile(r"\bpickle\.loads?\b|\bcPickle\b|"
                                  r"\byaml\.load\b(?!er)|\bmarshal\.loads\b|"
                                  r"ObjectInputStream|\bunserialize\s*\(|"
                                  r"Marshal\.load")),
    (SINK_EVAL, re.compile(r"\beval\s*\(|\bexec\s*\(|\bnew Function\s*\(|"
                           r"\bcompile\s*\(")),
    (SINK_FILE, re.compile(r"\bsend_file\s*\(|\bsend_from_directory\s*\(|"
                           r"\bsendFile\s*\(|\.readFile(?:Sync)?\s*\(")),
    (SINK_CRYPTO, re.compile(r"\bhashlib\.(?:md5|sha1)\b|\bmd5\s*\(|"
                             r"\bMessageDigest\b|\bDES\b|\bRC4\b|"
                             r"MODE_ECB|\bMath\.random\s*\(")),
    (SINK_SSRF, re.compile(r"\brequests\.(?:get|post|put|delete|request|head)\s*\(|"
                           r"\burllib\.request|\burlopen\s*\(|\bhttpx\.|"
                           r"\baxios\.|\bfetch\s*\(")),
    # Захардкоженные секреты: присваивание ключа/пароля строковому литералу
    # длиной >=6, плюс характерные форматы токенов и приватный ключ.
    (SINK_SECRET, re.compile(
        r"(?i)(?:api[_-]?key|secret|passwd|password|access[_-]?key|"
        r"auth[_-]?token|private[_-]?key)\s*[:=]\s*['\"][^'\"]{6,}['\"]"
        r"|AKIA[0-9A-Z]{16}"
        r"|\bsk-[A-Za-z0-9]{16,}"
        r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

# --- паттерны точек входа ----------------------------------------------------
# HTTP-роут через декоратор: Flask/FastAPI (@app.route/@app.get/@router.post).
_RX_DECORATOR_ROUTE = re.compile(
    r"@\w+\.(route|get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")
# HTTP-роут в стиле Express: app.get('/path', ...).
_RX_EXPRESS_ROUTE = re.compile(
    r"\b(?:app|router)\.(get|post|put|delete|patch|all|use)\s*\(\s*['\"]([^'\"]+)['\"]")
# Django urls: path('users/', ...) / re_path(...).
_RX_DJANGO_ROUTE = re.compile(r"\b(?:re_path|path|url)\s*\(\s*r?['\"]([^'\"]*)['\"]")
# Spring/JAX-RS: @GetMapping("/path") / @RequestMapping.
_RX_JVM_ROUTE = re.compile(
    r"@(Request|Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?"
    r"['\"]([^'\"]+)['\"]")
# CLI.
_RX_CLI = re.compile(r"@click\.command|argparse\.ArgumentParser|"
                     r"\bcommander\b|\byargs\b")
# Обработчики событий/очередей/функций.
_RX_HANDLER = re.compile(r"@\w*\.?task\b|def\s+lambda_handler\b|"
                         r"\bon_message\b|@(?:app|celery)\.task")
# Точка запуска процесса.
_RX_MAIN = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]|"
                      r"\bfunc\s+main\s*\(|public\s+static\s+void\s+main\b")

_SNIPPET_MAX = 160


def _snippet(line: str) -> str:
    return line.strip()[:_SNIPPET_MAX]


def scan_sinks(text: str, file: str) -> list[Sink]:
    """Находит опасные операции в тексте файла."""
    out: list[Sink] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, rx in _SINK_RX:
            if rx.search(line):
                out.append(Sink(kind=kind, file=file, line=lineno,
                                 snippet=_snippet(line)))
    return out


def scan_entry_points(text: str, file: str) -> list[EntryPoint]:
    """Находит точки входа (attack surface) в тексте файла."""
    out: list[EntryPoint] = []
    is_django_urls = file.endswith("urls.py")
    for lineno, line in enumerate(text.splitlines(), 1):
        for rx in (_RX_DECORATOR_ROUTE, _RX_EXPRESS_ROUTE, _RX_JVM_ROUTE):
            m = rx.search(line)
            if m:
                method, path = m.group(1), m.group(2)
                out.append(EntryPoint(kind=EP_HTTP_ROUTE, name=path, file=file,
                                      line=lineno, detail=method.upper()))
        if is_django_urls:
            m = _RX_DJANGO_ROUTE.search(line)
            if m:
                out.append(EntryPoint(kind=EP_HTTP_ROUTE, name=m.group(1),
                                      file=file, line=lineno, detail="django"))
        if _RX_CLI.search(line):
            out.append(EntryPoint(kind=EP_CLI, name=_snippet(line), file=file,
                                  line=lineno))
        if _RX_HANDLER.search(line):
            out.append(EntryPoint(kind=EP_HANDLER, name=_snippet(line),
                                  file=file, line=lineno))
        if _RX_MAIN.search(line):
            out.append(EntryPoint(kind=EP_MAIN, name=_snippet(line), file=file,
                                  line=lineno))
    return out
