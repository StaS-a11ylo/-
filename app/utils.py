"""Вспомогательные функции без зависимостей от aiogram."""

from __future__ import annotations

TELEGRAM_MESSAGE_LIMIT = 4096
ELLIPSIS = "…"


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Режет длинный ответ на части, которые принимает Telegram.

    Старается рвать текст по пустой строке, затем по переводу строки,
    затем по пробелу и только в крайнем случае — по символу.
    """
    if limit < 1:
        raise ValueError("limit должен быть больше нуля")
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []

    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[: limit + 1]
        cut = -1
        for separator in ("\n\n", "\n", " "):
            index = window.rfind(separator)
            if index > 0:
                cut = index + len(separator)
                break
        if cut <= 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return [part for part in parts if part]


def truncate(text: str, limit: int) -> str:
    """Обрезает текст до ``limit`` символов, добавляя многоточие."""
    if limit < 1:
        raise ValueError("limit должен быть больше нуля")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(ELLIPSIS))].rstrip() + ELLIPSIS


def mention(user) -> str:
    """Человекочитаемое имя пользователя для приветствий."""
    if user is None:
        return "друг"
    name = getattr(user, "first_name", None) or getattr(user, "username", None)
    return name or "друг"
