"""Память диалога: история сообщений по каждому чату.

Хранится в памяти процесса: этого достаточно для личного ассистента,
а при необходимости легко заменить на Redis/SQLite — интерфейс маленький.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Iterable

from .ai import Message

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class ChatHistory:
    """История сообщений с ограничением по длине и числу чатов."""

    def __init__(self, system_prompt: str, limit: int = 20, max_chats: int = 1000):
        if limit < 0:
            raise ValueError("limit не может быть отрицательным")
        if max_chats < 1:
            raise ValueError("max_chats должен быть больше нуля")
        self._system: Message = {"role": "system", "content": system_prompt}
        self._limit = limit
        self._max_chats = max_chats
        self._dialogs: OrderedDict[int, deque[Message]] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def chats(self) -> int:
        return len(self._dialogs)

    async def append(self, chat_id: int, role: str, content: str) -> None:
        """Добавляет сообщение в историю чата."""
        if role not in (ROLE_USER, ROLE_ASSISTANT, "system"):
            raise ValueError(f"Неизвестная роль: {role!r}")
        if not content:
            return
        async with self._lock:
            dialog = self._dialogs.get(chat_id)
            if dialog is None:
                dialog = deque(maxlen=self._limit or 1)
                self._dialogs[chat_id] = dialog
            dialog.append({"role": role, "content": content})
            self._dialogs.move_to_end(chat_id)
            self._evict_extra_chats()

    async def context(self, chat_id: int, extra: Iterable[Message] | None = None) -> list[Message]:
        """Возвращает сообщения для отправки в модель: system + история."""
        async with self._lock:
            dialog = list(self._dialogs.get(chat_id, ()))
        messages: list[Message] = [self._system]
        messages.extend(dialog)
        if extra:
            messages.extend(extra)
        return messages

    async def reset(self, chat_id: int) -> int:
        """Очищает историю чата, возвращает число удалённых сообщений."""
        async with self._lock:
            dialog = self._dialogs.pop(chat_id, None)
        return len(dialog) if dialog else 0

    async def drop_last(self, chat_id: int) -> bool:
        """Убирает последнее сообщение (например, если ответ модели не удался)."""
        async with self._lock:
            dialog = self._dialogs.get(chat_id)
            if not dialog:
                return False
            dialog.pop()
            if not dialog:
                self._dialogs.pop(chat_id, None)
            return True

    def _evict_extra_chats(self) -> None:
        while len(self._dialogs) > self._max_chats:
            chat_id, _ = self._dialogs.popitem(last=False)
            logger.debug("История чата %s вытеснена: превышен лимит MAX_CHATS", chat_id)
