"""Общие фикстуры и вспомогательные объекты для тестов."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    DeleteMessage,
    EditMessageText,
    GetMe,
    SendChatAction,
    SendMessage,
    SetMyCommands,
    TelegramMethod,
)
from aiogram.types import Chat, Message, Update, User

from app.config import Settings

BOT_ID = 424242
CHAT_ID = 100500
USER_ID = 777

GET_ME_RESULT = {
    "id": BOT_ID,
    "is_bot": True,
    "first_name": "Test Bot",
    "username": "test_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
    "supports_inline_queries": False,
}


class FakeSession(BaseSession):
    """Поддельная сессия Telegram: запоминает запросы и отвечает как настоящая."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self._last_message_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """В тестах файлы не скачиваются."""
        raise NotImplementedError
        yield b""  # pragma: no cover — делает функцию генератором

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.requests.append(method)
        payload = {"ok": True, "result": self._result(method)}
        response = self.check_response(
            bot=bot, method=method, status_code=200, content=json.dumps(payload)
        )
        return response.result

    # --------------------------------------------------------------- утилиты

    def _next_message_id(self) -> int:
        self._last_message_id += 1
        return self._last_message_id

    def _message(self, chat_id: int, text: str | None, message_id: int | None = None) -> dict:
        data: dict[str, Any] = {
            "message_id": message_id or self._next_message_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
        }
        if text is not None:
            data["text"] = text
        return data

    def _result(self, method: TelegramMethod[Any]) -> Any:
        if isinstance(method, SendMessage):
            return self._message(method.chat_id, method.text)
        if isinstance(method, EditMessageText):
            return self._message(method.chat_id, method.text, method.message_id)
        if isinstance(method, (DeleteMessage, SetMyCommands, SendChatAction)):
            return True
        if isinstance(method, GetMe):
            return GET_ME_RESULT
        return True

    # ------------------------------------------------------- удобные срезы

    @property
    def sent_texts(self) -> list[str]:
        return [m.text for m in self.requests if isinstance(m, SendMessage) and m.text]

    @property
    def edited_texts(self) -> list[str]:
        return [m.text for m in self.requests if isinstance(m, EditMessageText) and m.text]

    @property
    def last_text(self) -> str | None:
        """Последний текст, который увидел пользователь."""
        for method in reversed(self.requests):
            if isinstance(method, (SendMessage, EditMessageText)) and method.text:
                return method.text
        return None

    def clear(self) -> None:
        self.requests.clear()


@pytest.fixture
def env() -> dict[str, str]:
    """Минимальное окружение для Settings.from_env."""
    return {"BOT_TOKEN": "42:TEST-TOKEN", "API_KEY": "sk-test", "MODEL": "test-model"}


@pytest.fixture
def settings(env: dict[str, str]) -> Settings:
    return Settings.from_env(env)


@pytest.fixture
def bot() -> Bot:
    return Bot(token="42:TEST-TOKEN", session=FakeSession())


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher()


def make_user(*, is_bot: bool = False, user_id: int = USER_ID) -> User:
    return User(id=user_id, is_bot=is_bot, first_name="Тест")


def make_message(
    text: str | None = None,
    *,
    chat_id: int = CHAT_ID,
    message_id: int = 10,
    from_user: User | None = None,
    **extra: Any,
) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=from_user or make_user(),
        text=text,
        **extra,
    )


def make_update(message: Message, update_id: int = 1) -> Update:
    return Update(update_id=update_id, message=message)
