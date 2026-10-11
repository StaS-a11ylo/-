"""Тесты памяти диалога."""

from __future__ import annotations

import pytest

from app.history import ROLE_ASSISTANT, ROLE_USER, ChatHistory


async def test_context_starts_with_system_prompt() -> None:
    history = ChatHistory("Ты тестовый бот", limit=5)

    assert await history.context(1) == [{"role": "system", "content": "Ты тестовый бот"}]


async def test_messages_are_kept_in_order() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "привет")
    await history.append(1, ROLE_ASSISTANT, "здравствуй")

    context = await history.context(1)

    assert [m["content"] for m in context] == ["система", "привет", "здравствуй"]
    assert [m["role"] for m in context] == ["system", "user", "assistant"]


async def test_histories_of_chats_are_independent() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "первый чат")
    await history.append(2, ROLE_USER, "второй чат")

    assert [m["content"] for m in await history.context(1)] == ["система", "первый чат"]
    assert [m["content"] for m in await history.context(2)] == ["система", "второй чат"]


async def test_limit_drops_oldest_messages() -> None:
    history = ChatHistory("система", limit=2)
    await history.append(1, ROLE_USER, "раз")
    await history.append(1, ROLE_ASSISTANT, "два")
    await history.append(1, ROLE_USER, "три")

    context = await history.context(1)

    assert [m["content"] for m in context] == ["система", "два", "три"]


async def test_reset_clears_only_target_chat() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "раз")
    await history.append(2, ROLE_USER, "два")

    removed = await history.reset(1)

    assert removed == 1
    assert len(await history.context(1)) == 1
    assert len(await history.context(2)) == 2
    assert await history.reset(1) == 0


async def test_drop_last_removes_failed_question() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "вопрос")

    assert await history.drop_last(1) is True
    assert len(await history.context(1)) == 1
    assert await history.drop_last(1) is False


async def test_extra_messages_are_appended_to_context() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "история")

    context = await history.context(1, extra=[{"role": "user", "content": "ещё"}])

    assert [m["content"] for m in context] == ["система", "история", "ещё"]


async def test_old_chats_are_evicted() -> None:
    history = ChatHistory("система", limit=10, max_chats=2)
    for chat_id in (1, 2, 3):
        await history.append(chat_id, ROLE_USER, f"чат {chat_id}")

    assert history.chats == 2
    assert len(await history.context(1)) == 1  # самый старый чат забыт


async def test_empty_message_is_ignored() -> None:
    history = ChatHistory("система", limit=10)
    await history.append(1, ROLE_USER, "")

    assert history.chats == 0


async def test_unknown_role_raises() -> None:
    history = ChatHistory("система", limit=10)

    with pytest.raises(ValueError, match="роль"):
        await history.append(1, "moderator", "текст")


@pytest.mark.parametrize(("limit", "max_chats"), [(-1, 10), (10, 0)])
def test_invalid_constructor_arguments(limit: int, max_chats: int) -> None:
    with pytest.raises(ValueError):
        ChatHistory("система", limit=limit, max_chats=max_chats)
