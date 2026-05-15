# agentsec — мультиагентный анализ кода на уязвимости

MVP мультиагентной системы для пентест-анализа кодовых баз. Построено на LangGraph.

## Архитектура

Оркестрация — детерминированный `StateGraph` (LangGraph). LLM решает,
*что найдено*; граф решает, *что запускается* — специалисты не
пропускаются.

```
START → intake → (clarify?) → recon ─┬─→ specialist:injection ─┐
                                     ├─→ specialist:secrets   ─┤
                                     └─→ specialist:authnz    ─┘
                                                               │
                          consolidate ←──────────────────────┘
                               │
                          validate → gate → report → END
```

- **intake** — интерпретирует задачу на естественном языке (в т.ч. нечёткую);
  решает, нужно ли уточнение.
- **clarify** — задаёт вопрос пользователю через `ask_user` (интерактив).
- **recon** — детерминированная разведка: миньоны `explore_codebase`,
  `read_docs` и, по флагу, сканеры.
- **3 специалиста** — узлы графа, запускаются параллельно и ВСЕГДА:
  `injection`, `secrets`, `authnz`. Возвращают структурные `Finding`.
- **consolidate** — дедупликация находок по fingerprint, нумерация (F-001…).
- **validate** — агент-«скептик»: evidence-only проверка, отсев false
  positives, `status` + CVSS.
- **gate** — quality gate: вердикт PASS/NEEDS_REVIEW/FAIL по порогам
  severity; в интерактиве спрашивает, отдавать ли проект на сборку.
- **report** — итоговый markdown + структурный JSON.

Подробный план и архитектурные решения — в `docs/orchestrator-plan.md`.

**Уровни агентов:**
- **Оркестратор** — детерминированный граф (`agentsec/graph.py`): разведка,
  уточнения, делегирование специалистам, валидация, quality gate. Файлы не правит.
- **Специалисты** — каждый работает по своему классу уязвимостей. Инструменты:
  чтение/запись/редактирование файлов, grep/glob/ls, вызов миньонов. Запись —
  для написания тестов и PoC, с подтверждением пользователя.
- **Миньоны** — узкие сабагенты. `explore_codebase` (разведка кодовой базы),
  `read_docs` (чтение документации), `resolve_project_dependencies`
  (requirements/package.json/lock/go.mod), `search_dependency_vulnerabilities`
  (OSV/CVE по зависимостям), `sketch_callgraph` (грубый callgraph) и
  `run_deterministic_scanners` (semgrep/gitleaks/osv-scanner, если установлены).
  По умолчанию они не меняют код цели.

Специалисты и миньоны — самостоятельные ReAct-графы LangGraph. Узлы
оркестрирующего графа вызывают их напрямую (детерминированно), а не
через решение LLM-оркестратора.

Код возврата CLI работает как quality gate для CI: `0` — сборку можно
продолжать, `1` — найдено блокирующее / сборка не одобрена, `2` —
требуется ручная проверка.

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env      # и заполни ключ/эндпоинт/модель
```

LLM — любой OpenAI-совместимый бэкенд (OpenAI, OpenRouter, Ollama, vLLM).
Настраивается через `.env`: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL`.

## Запуск

```bash
# на встроенном уязвимом демо-приложении
python main.py --repo ./examples/vulnerable_app --task "Проведи аудит безопасности"

# на своём репозитории
python main.py --repo /path/to/target --task "Найди уязвимости в обработке ввода"

# сохранить markdown + json отчёт в reports/ и предварительно запустить scanners
python main.py --repo ./examples/vulnerable_app \
  --task "Проведи аудит безопасности" \
  --run-scanners --format md --format json --format html
```

Флаг `--yes` — авто-подтверждение записи файлов (для неинтерактивных прогонов).
Флаг `--output-dir` задаёт каталог отчётов, `--no-save` отключает сохранение,
`--format` можно повторять для `md`, `json`, `html`.

Детерминистические сканеры подключены как инструменты агентов и CLI-режим:

- `semgrep scan --config auto --json .`
- `gitleaks detect --no-git --report-format json`
- `osv-scanner --format json -r .`

Если бинарь не установлен, инструмент возвращает явный статус `unavailable`,
а прогон продолжается. Базовый MCP-конфиг лежит в `mcp/scanners.mcp.json`.

## Отчёты

`agentsec.reporting.save_report()` сохраняет текущий markdown-отчёт и
машиночитаемый JSON. Когда ветка B добавит `Finding`, функция уже принимает
`list[Finding]`/dict/dataclass/Pydantic и сериализует их в JSON; до этого
она best-effort парсит MVP markdown-формат.

## Eval

Минимальный harness:

```bash
# оценить готовый отчёт против эталона vulnerable_app
python3 eval/run_eval.py --report reports/<file>.md

# запустить анализ и сразу оценить stdout/stderr
python3 eval/run_eval.py --run
```

Эталонные проверки лежат в `eval/expected/vulnerable_app.json`. Они намеренно
простые: проверяют наличие ключевых сигналов для SQLi, command injection,
path traversal, IDOR, hardcoded secrets и MD5, чтобы быстро сравнивать модели
и промпты между прогонами.

`examples/vulnerable_app/` — намеренно уязвимое приложение (SQLi, command
injection, path traversal, IDOR, хардкод-секреты, MD5) для проверки системы.

## Тесты

Юнит-тесты на stdlib `unittest` (без сети и без LLM):

```bash
python -m unittest discover -s tests
```

Покрывают: схему находок (парсинг, дедупликация, quality gate), рендер и
сохранение отчётов, структуру графа, детерминированные узлы и
интерактивные узлы `clarify`/`gate` (с подменённым `ask_user`).

## Структура

```
main.py                      CLI-точка входа, exit-code = quality gate
agentsec/
  config.py                  глобальная конфигурация рантайма
  llm.py                     универсальная фабрика LLM (OpenAI-совместимый API)
  prompts.py                 системные промпты всех агентов
  schema.py                  Finding, Coverage, дедуп, парсер, compute_verdict
  state.py                   AnalysisState — состояние графа оркестрации
  graph.py                   детерминированный StateGraph оркестрации
  tools/
    filesystem.py            read/write/edit/ls/glob/grep (в пределах корня анализа)
    interaction.py           ask_user
    dependencies.py          разбор requirements/package.json/lock/go.mod + OSV
    callgraph.py             грубый static callgraph для Python/JS/TS
    scanners.py              semgrep/gitleaks/osv-scanner wrappers
  agents/
    minions.py               миньоны explore_codebase, read_docs, …
    specialists.py           специалисты по классам уязвимостей
    validator.py             агент-валидатор («скептик»)
    orchestrator.py          тонкая обёртка-запуск графа
  reporting.py               рендер и сохранение markdown/json/html отчётов
docs/
  orchestrator-plan.md       план работ и архитектурные решения
eval/
  run_eval.py                harness для сравнения отчёта с эталоном
mcp/
  scanners.mcp.json          пример MCP-конфига для scanners
```

## Roadmap

Сделано в текущей итерации (детерминированный оркестратор): параллельный
fan-out специалистов, агент-валидатор, структурная схема `Finding`,
трекинг покрытия, recon-фаза, quality gate с exit-code.

Отложено (подробнее — `docs/orchestrator-plan.md`):

- **Интеграция с трекером** — создание issue в GitHub/Jira; сейчас
  блокировка реализована через exit-code CLI.
- **Полная структура evidence-каталога** per finding.
- **Детерминистические сканеры через MCP** — полноценный MCP server/runtime
  вместо CLI wrapper.
- **Песочница исполнения** — изолированный контейнер для запуска цели и PoC.
- **`--resume` графа** из сохранённого state (память между прогонами).
- **Eval по структурным находкам** (CWE + файл) → precision/recall вместо
  substring-матча; knowledge-pack-и для специалистов.
```
