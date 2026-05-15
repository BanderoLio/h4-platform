"""Универсальная фабрика LLM поверх OpenAI-совместимого API.

Работает с OpenAI, OpenRouter, Ollama, vLLM и любым бэкендом с
OpenAI-совместимым эндпоинтом — достаточно поменять OPENAI_BASE_URL
и MODEL в окружении, код агентов не меняется.
"""
from __future__ import annotations

import os
import time

from langchain_openai import ChatOpenAI


def _short_err(err: Exception) -> str:
    """Короткое представление ошибки — 429-ответы провайдера огромные."""
    text = " ".join(str(err).split())
    return text if len(text) <= 160 else text[:160] + "…"


def _retry_after_seconds(err: Exception) -> float | None:
    """Извлекает рекомендованную паузу из 429-ответа провайдера, если она есть.

    OpenRouter кладёт подсказку и в тело (error.metadata.retry_after_seconds),
    и в HTTP-заголовок Retry-After. Уважать её важно: при rate-limit провайдер
    может требовать паузу в десятки секунд — короткий бэкофф её не перекроет.
    """
    body = getattr(err, "body", None)
    if isinstance(body, dict):
        meta = (body.get("error") or {}).get("metadata") or {}
        hint = meta.get("retry_after_seconds")
        if hint:
            try:
                return float(hint)
            except (TypeError, ValueError):
                pass
    response = getattr(err, "response", None)
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except (TypeError, ValueError):
                pass
    return None


class ResilientChatOpenAI(ChatOpenAI):
    """ChatOpenAI с ретраями на транзиентные ошибки провайдера.

    OpenRouter (особенно бесплатный пул) регулярно отвечает 500/429 —
    причём иногда прямо в теле ответа со статусом HTTP 200, из-за чего
    штатные ретраи openai-клиента не срабатывают. Здесь повтор делается
    на уровне _generate, поэтому покрывает и оркестратора, и специалистов,
    и миньонов — все они ходят в LLM через этот класс. При rate-limit
    пауза берётся из подсказки Retry-After, а не из фиксированного бэкоффа.
    """

    transient_retries: int = 6
    transient_backoff: float = 2.0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last_err: Exception | None = None
        for attempt in range(1, self.transient_retries + 1):
            try:
                return super()._generate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as err:  # noqa: BLE001 — ретраим любую ошибку провайдера
                last_err = err
                if attempt == self.transient_retries:
                    break
                hint = _retry_after_seconds(err)
                # rate-limit -> ждём столько, сколько просит провайдер (+1с буфер);
                # иначе — линейный бэкофф.
                wait = (hint + 1.0) if hint else self.transient_backoff * attempt
                print(
                    f"      ! ошибка LLM: {_short_err(err)}. Повтор "
                    f"{attempt}/{self.transient_retries - 1} через {wait:.0f}с"
                )
                time.sleep(wait)
        raise last_err  # type: ignore[misc]


def build_llm(temperature: float = 0.0) -> ResilientChatOpenAI:
    """Собирает LLM-клиент из переменных окружения."""
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    # Локальным бэкендам (Ollama и пр.) ключ не нужен — подставляем заглушку.
    api_key = os.environ.get("OPENAI_API_KEY") or "not-needed"
    model = os.environ.get("MODEL", "gpt-4o-mini")
    return ResilientChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
    )
