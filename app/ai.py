"""Клиент LLM по OpenAI-совместимому протоколу.

Подходит для OpenAI, OpenRouter, Groq, Together, Ollama, LM Studio и любых
других сервисов, у которых есть эндпоинт ``POST {base_url}/chat/completions``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Sequence

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

Message = dict[str, str]

RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
MAX_ERROR_DETAIL = 300


class LLMError(RuntimeError):
    """Ошибка обращения к LLM. Текст пригоден для показа пользователю."""


def _build_payload(settings: Settings, messages: Sequence[Message], *, stream: bool) -> dict:
    return {
        "model": settings.model,
        "messages": list(messages),
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "stream": stream,
    }


def _error_detail(response: httpx.Response) -> str:
    """Достаёт человекочитаемое описание ошибки из тела ответа."""
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        text = response.text.strip()
        return text[:MAX_ERROR_DETAIL] if text else ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:MAX_ERROR_DETAIL]
        if isinstance(error, str):
            return error[:MAX_ERROR_DETAIL]
        if data.get("detail"):
            return str(data["detail"])[:MAX_ERROR_DETAIL]
    return ""


def _describe_status(response: httpx.Response) -> str:
    detail = _error_detail(response)
    hints = {
        400: "проверьте название модели и параметры запроса",
        401: "проверьте API_KEY",
        403: "ключ не имеет доступа к этой модели",
        404: "проверьте BASE_URL и название модели",
        429: "слишком много запросов или закончилась квота",
    }
    hint = hints.get(response.status_code)
    message = f"Сервис ответил ошибкой {response.status_code}"
    if hint:
        message += f" — {hint}"
    if detail:
        message += f". {detail}"
    return message


def _parse_content(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("Сервис вернул ответ без вариантов (choices).")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        # Некоторые провайдеры отдают контент списком частей.
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Сервис вернул пустой ответ. Попробуйте переформулировать вопрос.")
    return content.strip()


class LLMClient:
    """Асинхронный клиент к chat completions с ретраями и стримингом."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout, connect=10.0),
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            transport=transport,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ API

    async def complete(self, messages: Sequence[Message]) -> str:
        """Возвращает ответ модели целиком."""
        payload = _build_payload(self._settings, messages, stream=False)
        data = await self._request_json(payload)
        return _parse_content(data)

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Отдаёт ответ модели по частям (по мере генерации)."""
        yield_any = False
        for attempt in range(self._settings.max_retries + 1):
            try:
                async for chunk in self._stream_once(messages):
                    yield_any = True
                    yield chunk
                return
            except LLMError:
                raise
            except (httpx.HTTPError, httpx.StreamError) as exc:
                if yield_any or attempt >= self._settings.max_retries:
                    raise LLMError(
                        "Не удалось получить ответ от сервиса. Попробуйте ещё раз позже."
                    ) from exc
                await self._sleep_before_retry(attempt, reason=str(exc))
            except _RetryableStatus as exc:
                if yield_any or attempt >= self._settings.max_retries:
                    raise LLMError(str(exc)) from exc
                await self._sleep_before_retry(attempt, reason=str(exc))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------- Внутреннее

    async def _request_json(self, payload: dict) -> dict:
        last_error: LLMError | None = None
        for attempt in range(self._settings.max_retries + 1):
            try:
                async with self._semaphore:
                    response = await self._client.post(self._settings.endpoint, json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in RETRYABLE_STATUSES and attempt < self._settings.max_retries:
                    last_error = LLMError(_describe_status(exc.response))
                    await self._sleep_before_retry(attempt, reason=last_error.args[0])
                    continue
                raise LLMError(_describe_status(exc.response)) from exc
            except httpx.TimeoutException as exc:
                last_error = LLMError("Сервис не ответил вовремя. Попробуйте ещё раз позже.")
                if attempt >= self._settings.max_retries:
                    raise last_error from exc
                await self._sleep_before_retry(attempt, reason="таймаут")
            except httpx.HTTPError as exc:
                last_error = LLMError("Не удалось связаться с сервисом. Проверьте BASE_URL и сеть.")
                if attempt >= self._settings.max_retries:
                    raise last_error from exc
                await self._sleep_before_retry(attempt, reason=str(exc))
            except ValueError as exc:  # битый JSON в ответе
                raise LLMError("Сервис вернул некорректный JSON.") from exc
        raise last_error or LLMError("Не удалось получить ответ от сервиса.")

    async def _stream_once(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        payload = _build_payload(self._settings, messages, stream=True)
        async with (
            self._semaphore,
            self._client.stream("POST", self._settings.endpoint, json=payload) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                description = _describe_status(response)
                if response.status_code in RETRYABLE_STATUSES:
                    raise _RetryableStatus(description)
                raise LLMError(description)

            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                async for chunk in _iter_sse_lines(response.aiter_lines()):
                    yield chunk
                return

            # Провайдер проигнорировал stream=true и ответил обычным JSON —
            # отдаём ответ целиком, чтобы пользователь не получил «пустой ответ».
            body = (await response.aread()).decode(errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                async for chunk in _iter_sse_lines(_aiter_lines(body)):
                    yield chunk
            else:
                yield _parse_content(data)

    async def _sleep_before_retry(self, attempt: int, *, reason: str = "") -> None:
        delay = min(2**attempt, 8) + random.uniform(0, 0.5)
        logger.warning(
            "Повтор запроса к LLM через %.1f c (причина: %s)", delay, reason or "неизвестно"
        )
        await asyncio.sleep(delay)


class _RetryableStatus(Exception):
    """Внутренний сигнал: статус, который имеет смысл повторить в стриминге."""


DONE = object()


async def _aiter_lines(text: str) -> AsyncIterator[str]:
    """Строчный «поток» из готового текста — для фолбэка на не-SSE ответ."""
    for line in text.splitlines():
        yield line


async def _iter_sse_lines(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Разбирает строки SSE-потока OpenAI и отдаёт куски текста."""
    async for line in lines:
        parsed = _parse_sse_line(line)
        if parsed is DONE:
            return
        if parsed is not None:
            yield parsed


def _parse_sse_line(raw_line: str) -> str | object | None:
    """Возвращает текст чанка, ``DONE`` в конце потока или ``None``, если строка пустая."""
    line = raw_line.strip()
    if not line or line.startswith(":") or not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data:
        return None
    if data == "[DONE]":
        return DONE
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        logger.debug("Пропущен некорректный SSE-чанк: %r", data[:120])
        return None

    choices = event.get("choices") or []
    if not choices:
        return None
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) and content else None
