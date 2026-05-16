# План: история сессий агентов + продолжение (как в Cursor IDE)

## Context

Сейчас система — это **детерминированный LangGraph-оркестратор**, который запускается одним
вызовом `run_analysis(task)` ([agentsec/agents/orchestrator.py](agentsec/agents/orchestrator.py)),
прогоняет граф `intake → recon → 3 специалиста → consolidate → validate → gate → report`
end-to-end и возвращает финальное состояние. Граф **stateless**: нет id прогона, нет
сохранения состояния, нет чекпоинтинга. Интерактивные точки (`_clarify`, `_gate`) читают
ответ из stdin — это работает только в CLI.

Нужна фича как в Cursor IDE: пользователь заходит во фронт, видит список прошлых сканов
(сессий), открывает любой и продолжает его — контекст не теряется. FastAPI-бэкенд с ручками
для фронта живёт в **отдельном репозитории** (не в этом workspace) и вызывает функцию скана
из оркестратора.

Решение делится на две фазы. **Фаза 1** (дёшево, высокая ценность) — история сессий +
возобновление скана, поставленного на паузу на интерактивной точке (уточняющий вопрос,
решение gate). **Фаза 2** (дороже, опционально) — дозапросы по завершённому скану. Пользователь
просил «ровно как в Cursor, но только если не ОЧЕНЬ сложно и дорого» → Фаза 1 закрывает
основной UX дёшево; Фаза 2 чётко отделена и выключена флагом.

Почему именно так: LangGraph **штатно** поддерживает паузу/возобновление через
`interrupt()` + чекпоинтер с `thread_id`. Это ровно механизм «продолжить с того же места,
не забыв контекст» — состояние графа целиком сохраняется в SQLite и восстанавливается.
Не нужно переписывать граф в чат-бота.

---

## Часть A — изменения в этом репозитории (оркестратор)

### A1. `requirements.txt`
Добавить одну зависимость (БД-чекпоинтер LangGraph):
```
langgraph-checkpoint-sqlite>=2.0,<3.0
```
FastAPI / SQLAlchemy / ORM **не добавляем** — для таблицы `sessions` хватает stdlib `sqlite3`.
Примечание: в `./venv` стоит `langgraph 1.2.0` — с `interrupt()` и `compile(checkpointer=...)`
совместимо; пин `langgraph>=0.3,<2.0` менять не нужно.

### A2. `agentsec/config.py` — новые поля в `Config`
- `server_mode: bool = False` — в `True` узлы `_clarify`/`_gate` используют `interrupt()`
  вместо stdin. CLI его никогда не ставит → поведение CLI не меняется.
- `session_db_path: Path = Path("agentsec_sessions.db")` — один SQLite-файл и для
  чекпоинтера, и для метаданных сессий.
- `enable_followup: bool = False` — флаг Фазы 2 (по умолчанию выкл).

Разделение: `interactive` решает *задавать ли вопрос*, `server_mode` решает *как задавать*
(HTTP-interrupt vs stdin).

### A3. `agentsec/graph.py` — узлы с поддержкой `interrupt()` + чекпоинтер
- Импорт: `from langgraph.types import interrupt`.
- `_clarify` ([graph.py:86](agentsec/graph.py#L86)): ветка по `CONFIG.server_mode` —
  `answer = interrupt({"type": "clarify", "question": question})` в server-режиме,
  иначе прежний `ask_user.invoke(...)`.
- `_gate` ([graph.py:203](agentsec/graph.py#L203)): аналогично, payload
  `{"type": "gate", "question": prompt, "verdict": verdict}`.
  `compute_verdict` стоит до `interrupt()` — узел при возобновлении выполняется заново
  целиком; функция чистая и дешёвая, повторный вызов безопасен. Дорогую/неидемпотентную
  работу до `interrupt()` не ставить.
- `build_graph(checkpointer=None)` ([graph.py:246](agentsec/graph.py#L246)):
  `return graph.compile(checkpointer=checkpointer)`. `checkpointer=None` идентичен
  текущему `compile()` — CLI-путь не меняется.

### A4. Новый пакет `agentsec/persistence/`
**`store.py`** — абстракция хранилища (для будущего перехода на Postgres):
- `SessionStore` (ABC): `create_session`, `get_session`, `list_sessions(limit, offset)`,
  `update_session(id, **fields)`.
- `SessionRecord` (dataclass) — зеркало таблицы.
- `SqliteSessionStore(SessionStore)` — на stdlib `sqlite3`, `check_same_thread=False`,
  одно соединение под `threading.Lock`, `PRAGMA journal_mode=WAL`. Открывает тот же файл
  `CONFIG.session_db_path`.

Таблица `sessions` (`CREATE TABLE IF NOT EXISTS`):
| колонка | тип | примечание |
|---|---|---|
| `id` | TEXT PK | uuid4 hex; он же `thread_id` LangGraph |
| `title` | TEXT | первые ~60 символов задачи |
| `repo` | TEXT | путь к репозиторию |
| `task` | TEXT | исходная задача |
| `status` | TEXT | `running` / `awaiting_input` / `completed` / `failed` |
| `interrupt_type` | TEXT NULL | `clarify` / `gate` когда `awaiting_input` |
| `interrupt_payload` | TEXT NULL | JSON значения `interrupt()` (вопрос для пользователя) |
| `verdict` | TEXT NULL | JSON-сводка вердикта |
| `report_md` | TEXT NULL | финальный отчёт (денормализован для быстрой истории) |
| `error` | TEXT NULL | текст исключения при `failed` |
| `created_at` / `updated_at` | TEXT | ISO-таймстемпы |

Метаданные `sessions` и таблицы чекпоинтера LangGraph (`checkpoints`, `writes`, …) лежат
в **одном файле**, но это разные таблицы — не конфликтуют. Переход на Postgres = замена
`SqliteSessionStore`→`PostgresSessionStore` и `SqliteSaver`→`PostgresSaver`, код
оркестратора не трогается.

**`checkpointer.py`** — фабрика чекпоинтера:
```python
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
def make_checkpointer(db_path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)   # синглтон процесса, держим открытым
```
Берём **синхронный `SqliteSaver`** (не `AsyncSqliteSaver`): граф вызывается синхронно
`graph.invoke()` в фоновом потоке.

### A5. `agentsec/agents/orchestrator.py` — новая сигнатура `run_analysis`
```python
def run_analysis(task=None, *, thread_id=None, resume=None, checkpointer=None) -> dict:
    graph = build_graph(checkpointer=checkpointer)
    config = {"recursion_limit": CONFIG.recursion_limit}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}
    if resume is not None:
        result = graph.invoke(Command(resume=resume), config)
    else:
        result = graph.invoke({"task": task, "repo": str(CONFIG.analysis_root)}, config)
    return result
```
`run(task)` оставить для обратной совместимости. CLI вызывает `run_analysis(task)` без
`thread_id`/`checkpointer` → поведение идентично текущему.
Определение паузы vs завершения: после `invoke` при наличии чекпоинтера проверять
`graph.get_state(config).next` и ключ `"__interrupt__"` в результате.

### A6. Новый файл `agentsec/session.py` — фасад жизненного цикла сессии
Единственный модуль, который импортирует внешний FastAPI-репозиторий. Связывает
store + checkpointer + orchestrator; сам оркестратор о сессиях ничего не знает.
- `start_session(task, repo, *, interactive=True) -> str`
- `resume_session(session_id, answer) -> None`
- `get_session(session_id) -> SessionRecord`
- `list_sessions(limit=50, offset=0) -> list[SessionRecord]`
- `_run(...)` — внутренний драйвер: ставит `CONFIG.server_mode=True`,
  `CONFIG.interactive`, `CONFIG.analysis_root`; вызывает `run_analysis`; по результату
  пишет `awaiting_input` (+ `interrupt_payload`) / `completed` (+ `verdict`, `report_md`)
  / `failed` (+ `error`).

**Конкуренция:** `CONFIG` — мутируемый глобальный синглтон, при параллельных сканах в
потоках это гонка. Для Фазы 1 — **единственный воркер-поток + `queue.Queue`**, сканы
выполняются по одному. Этого достаточно и это просто. Правильное решение (per-run
`Config` через `contextvars` или явная передача) — отложено, отмечено как граница
масштабирования.

### A7. `main.py` — функциональных изменений не требуется
CLI не ставит `server_mode`, `run_analysis(task)` сохраняет старую форму вызова.

---

## Часть B — контракт API для внешнего FastAPI-репозитория

**Импорт:** оркестратор ставится как пакет (editable / path-зависимость) в окружение
FastAPI-репо. FastAPI импортирует **только `agentsec.session`**:
```python
from agentsec.session import start_session, resume_session, get_session, list_sessions
```

**Фоновое выполнение:** скан идёт минуты — нельзя держать HTTP-запрос. Фаза 1:
FastAPI `BackgroundTasks` + единственный воркер-поток оркестратора (A6). `POST /sessions`
кладёт задачу в очередь и сразу возвращает `202` с `session_id`. Без Redis/Celery.

**Пауза → HTTP:** пауза на `interrupt()` — не HTTP-событие. Фоновый прогон просто
завершает `invoke()` раньше, фасад ставит `status=awaiting_input` + `interrupt_payload`,
поток заканчивается. Клиент узнаёт о паузе **поллингом** `GET /sessions/{id}/status`.
Ответ пользователя (`POST /sessions/{id}/resume`) ставит в очередь новый фоновый прогон
`graph.invoke(Command(resume=answer), ...)` — LangGraph поднимает состояние из чекпоинта.

**Эндпоинты:**
| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/sessions` | Старт скана. Body `{task, repo, interactive}`. → `202 {session_id, status}` |
| `GET` | `/sessions` | История. Query `limit`, `offset`. → список `{id, title, repo, task, status, verdict_summary, created_at, updated_at}` |
| `GET` | `/sessions/{id}` | Детали: полный `SessionRecord` + `report_md` (если completed) + блок `interrupt` (если awaiting_input) |
| `POST` | `/sessions/{id}/resume` | Ответ на interrupt. Body `{answer}`. Только при `awaiting_input`, иначе `409`. → `202` |
| `GET` | `/sessions/{id}/status` | Лёгкий поллинг: `{status, interrupt_type?}` |
| `GET` | `/sessions/{id}/events` | (опц.) SSE-стрим переходов статуса; Фаза 1 может быть только-поллинг |

Машина состояний: `running → awaiting_input → running → completed` (или `→ failed`).
Единственный переход, инициируемый клиентом, — `/resume`.

---

## Часть C — Фаза 2 (дозапросы по завершённому скану), опционально

Эскиз: после `completed` — `POST /sessions/{id}/ask` `{question}`. Сервер строит лёгкого
ReAct-агента (`create_react_agent` — уже используется специалистами) с read-only
инструментами (filesystem/callgraph/dependencies-миньоны) и контекстом прошлого скана
(`recon`, `validated_findings`, `verdict`, `report_md` из чекпоинта). Отдельный namespace
`thread_id` (`{id}:followup`) для памяти диалога.

**Честная оценка стоимости:** Фаза 1 переиспользует тот же граф, почти без новых LLM-затрат.
Фаза 2 — **новый вызов агента на каждый вопрос** (свой ReAct-цикл, чтение файлов, несколько
вызовов LLM), плюс риск раздувания контекста токенами. Это заметно больше кода и постоянных
затрат. **Рекомендация:** поставить Фазу 1, держать `CONFIG.enable_followup=False`, эндпоинт
`/ask` за этим флагом; Фазу 2 делать отдельным проектом.

---

## Критические файлы
- [agentsec/graph.py](agentsec/graph.py) — `interrupt()` в `_clarify`/`_gate`, `build_graph(checkpointer=)`
- [agentsec/agents/orchestrator.py](agentsec/agents/orchestrator.py) — новая сигнатура `run_analysis`
- [agentsec/config.py](agentsec/config.py) — флаги `server_mode`, `session_db_path`, `enable_followup`
- `agentsec/persistence/store.py` + `checkpointer.py` — **новые**: хранилище и чекпоинтер
- `agentsec/session.py` — **новый**: фасад сессий + очередь воркера
- [requirements.txt](requirements.txt) — `langgraph-checkpoint-sqlite`

## Порядок реализации
1. `requirements.txt` → `pip install -r requirements.txt`.
2. `config.py` — флаги.
3. `persistence/store.py` + `checkpointer.py`.
4. `graph.py` — `interrupt()`-ветки, `build_graph(checkpointer=)`.
5. `orchestrator.py` — новая сигнатура.
6. `session.py` — фасад + очередь.
7. (Внешний репо) FastAPI-эндпоинты поверх `agentsec.session`.
8. Фаза 2 — только при отдельном одобрении.

## Верификация
**Без регрессий (проверять первым):**
- `python main.py --repo ./examples/vulnerable_app --task "..."` интерактивно — stdin-вопросы
  `_clarify`/`_gate` работают как раньше (`server_mode=False`).
- `python main.py --non-interactive ...` — без вопросов, коды возврата прежние.
- Прогнать `tests/` — без новых падений.

**Чекпоинтер / возобновление:**
- `start_session(...)` с задачей, вызывающей уточнение → `status=awaiting_input`,
  в `interrupt_payload` лежит вопрос.
- `resume_session(id, answer)` → скан продолжается, в финальном состоянии `clarifications`
  содержит ответ, `status=completed`. То же для interrupt `gate`.
- Убить процесс между паузой и возобновлением, перезапустить, вызвать `resume` →
  чекпоинт в SQLite корректно продолжает прогон (проверка персистентности).

**Хранилище:** `sqlite3 agentsec_sessions.db ".tables"` — `sessions` и таблицы
чекпоинтера сосуществуют; `list_sessions` сортирует новейшие первыми, пагинация работает.

**API (внешний репо):** `POST /sessions` возвращает `202` мгновенно; поллинг
`/status` показывает `running → awaiting_input`; `/resume` при неверном статусе → `409`;
`GET /sessions/{id}` отдаёт `report_md` после `completed`.

**Конкуренция:** запустить две сессии подряд — при очереди воркера они идут
последовательно, `CONFIG.analysis_root` одной не портит другую.
