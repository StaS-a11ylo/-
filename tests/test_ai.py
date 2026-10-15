"""Тесты клиента LLM на поддельном транспорте httpx."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai import LLMClient, LLMError
from app.config import Settings

MESSAGES = [{"role": "user", "content": "привет"}]
SSE_HEADERS = {"content-type": "text/event-stream"}


def sse(*chunks: str) -> bytes:
    """Собирает SSE-ответ как у OpenAI-совместимых провайдеров."""
    lines = []
    for chunk in chunks:
        payload = {"choices": [{"delta": {"content": chunk}}]}
        lines.append(f"data: {json.dumps(payload)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


@pytest.fixture
def make_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Callable[..., LLMClient]:
    """Фабрика клиентов с поддельным транспортом и без реальных задержек."""

    async def no_sleep(self: LLMClient, attempt: int, *, reason: str = "") -> None:
        return None

    monkeypatch.setattr(LLMClient, "_sleep_before_retry", no_sleep)

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> LLMClient:
        return LLMClient(settings, transport=httpx.MockTransport(handler))

    return factory


async def test_complete_returns_text(make_client) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return chat_response("привет, человек")

    client = make_client(handler)
    try:
        answer = await client.complete(MESSAGES)
    finally:
        await client.aclose()

    assert answer == "привет, человек"
    assert seen[0]["model"] == "test-model"
    assert seen[0]["stream"] is False
    assert seen[0]["messages"] == MESSAGES


async def test_complete_sends_authorization_header(make_client) -> None:
    headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers)
        return chat_response("ок")

    client = make_client(handler)
    try:
        await client.complete(MESSAGES)
    finally:
        await client.aclose()

    assert headers[0]["authorization"] == "Bearer sk-test"
    assert headers[0]["content-type"] == "application/json"


async def test_complete_supports_content_as_parts(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "часть один "},
                                {"type": "text", "text": "часть два"},
                            ]
                        }
                    }
                ]
            },
        )

    client = make_client(handler)
    try:
        answer = await client.complete(MESSAGES)
    finally:
        await client.aclose()

    assert answer == "часть один часть два"


async def test_complete_without_choices_raises(make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"choices": []}))
    try:
        with pytest.raises(LLMError, match="choices"):
            await client.complete(MESSAGES)
    finally:
        await client.aclose()


async def test_complete_with_blank_content_raises(make_client) -> None:
    client = make_client(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})
    )
    try:
        with pytest.raises(LLMError, match="пустой ответ"):
            await client.complete(MESSAGES)
    finally:
        await client.aclose()


async def test_unauthorized_error_is_user_friendly(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    client = make_client(handler)
    try:
        with pytest.raises(LLMError) as exc_info:
            await client.complete(MESSAGES)
    finally:
        await client.aclose()

    message = str(exc_info.value)
    assert "401" in message
    assert "API_KEY" in message
    assert "Invalid API key" in message


async def test_rate_limit_is_retried_then_succeeds(make_client) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return chat_response("получилось")

    client = make_client(handler)
    try:
        answer = await client.complete(MESSAGES)
    finally:
        await client.aclose()

    assert answer == "получилось"
    assert len(attempts) == 3


async def test_retries_are_limited(make_client) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(500, json={"error": {"message": "boom"}})

    client = make_client(handler)
    try:
        with pytest.raises(LLMError):
            await client.complete(MESSAGES)
    finally:
        await client.aclose()

    assert len(attempts) == 3  # первая попытка + MAX_RETRIES


async def test_network_error_is_wrapped(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(LLMError, match="связаться"):
            await client.complete(MESSAGES)
    finally:
        await client.aclose()


async def test_stream_yields_chunks(make_client) -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, content=sse("Привет", ", ", "мир!"), headers=SSE_HEADERS)

    client = make_client(handler)
    try:
        chunks = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()

    assert chunks == ["Привет", ", ", "мир!"]
    assert "".join(chunks) == "Привет, мир!"
    assert payloads[0]["stream"] is True


async def test_stream_falls_back_to_plain_json_response(make_client) -> None:
    """Провайдер проигнорировал stream=true — ответ всё равно доходит до пользователя."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "без стрима"}}]},
            headers={"content-type": "application/json"},
        )

    client = make_client(handler)
    try:
        chunks = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()

    assert chunks == ["без стрима"]


async def test_stream_parses_sse_without_content_type(make_client) -> None:
    """Некоторые сервисы не выставляют text/event-stream — разбираем текст как SSE."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse("почти стрим"))

    client = make_client(handler)
    try:
        chunks = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()

    assert chunks == ["почти стрим"]


async def test_stream_ignores_noise_and_broken_chunks(make_client) -> None:
    body = (
        ": keep-alive\n\n"
        "event: message\n"
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: not-json\n\n"
        'data: {"choices":[{"delta":{"content":"живой"}}]}\n\n'
        "data: [DONE]\n\n"
        'data: {"choices":[{"delta":{"content":"после DONE"}}]}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(), headers=SSE_HEADERS)

    client = make_client(handler)
    try:
        chunks = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()

    assert chunks == ["живой"]


async def test_stream_error_status_raises(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad model"}})

    client = make_client(handler)
    try:
        with pytest.raises(LLMError, match="bad model"):
            _ = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()


async def test_stream_retries_before_first_chunk(make_client) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "перегрузка"}})
        return httpx.Response(200, content=sse("окей"), headers=SSE_HEADERS)

    client = make_client(handler)
    try:
        chunks = [chunk async for chunk in client.stream(MESSAGES)]
    finally:
        await client.aclose()

    assert chunks == ["окей"]
    assert len(attempts) == 2


async def test_client_works_as_context_manager(make_client) -> None:
    client = make_client(lambda request: chat_response("привет"))

    async with client as opened:
        assert await opened.complete(MESSAGES) == "привет"
