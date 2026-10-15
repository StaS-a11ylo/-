"""Хендлеры Telegram: команды и генерация ответов."""

from __future__ import annotations

import html
import logging
import time
from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from .ai import LLMClient, LLMError
from .config import Settings
from .history import ROLE_ASSISTANT, ROLE_USER, ChatHistory
from .utils import TELEGRAM_MESSAGE_LIMIT, mention, split_message, truncate

logger = logging.getLogger(__name__)

PLACEHOLDER = "🤔 Думаю…"
CUT_NOTE = "⚠️ Ответ оборвался — не удалось получить полный текст."
STREAM_EDIT_INTERVAL = 1.2
MAX_QUESTION_LENGTH = TELEGRAM_MESSAGE_LIMIT - 100

HELP_TEXT = (
    "Я отвечаю на вопросы с помощью большой языковой модели.\n\n"
    "• просто напиши сообщение — я отвечу;\n"
    "• /reset — забыть контекст текущего диалога;\n"
    "• /model — какая модель сейчас используется;\n"
    "• /help — эта справка."
)


async def _safe_edit(message: Message, text: str) -> None:
    """Правка сообщения, устойчивая к «message is not modified» и лимитам."""
    try:
        await message.edit_text(truncate(text, TELEGRAM_MESSAGE_LIMIT))
    except TelegramBadRequest as exc:
        logger.debug("Не удалось отредактировать сообщение: %s", exc)


def _clean(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_QUESTION_LENGTH:
        text = text[:MAX_QUESTION_LENGTH]
    return text


async def _answer_streaming(
    message: Message, client: LLMClient, context: list[dict[str, str]]
) -> str:
    """Стримит ответ в одно сообщение, дописывая его по мере генерации."""
    placeholder = await message.reply(PLACEHOLDER)
    buffer = ""
    shown = PLACEHOLDER
    last_edit = 0.0
    interrupted: str | None = None
    try:
        async for chunk in client.stream(context):
            buffer += chunk
            now = time.monotonic()
            if len(buffer) >= TELEGRAM_MESSAGE_LIMIT:
                continue  # дальше копим молча: не влезает в одно сообщение
            if now - last_edit >= STREAM_EDIT_INTERVAL and buffer != shown:
                shown = buffer
                last_edit = now
                await _safe_edit(placeholder, buffer)
    except LLMError as exc:
        if not buffer.strip():
            # Ответа не было вовсе — убираем заглушку, чтобы не было «немого» сообщения.
            with suppress(TelegramBadRequest):
                await placeholder.delete()
            raise
        interrupted = str(exc)

    parts = split_message(buffer)
    if not parts:
        raise LLMError("Сервис вернул пустой ответ. Попробуйте переформулировать вопрос.")
    if interrupted:
        parts[-1] = f"{parts[-1]}\n\n{CUT_NOTE}"

    if parts[0] != shown:
        await _safe_edit(placeholder, parts[0])
    for part in parts[1:]:
        await message.reply(part)
    if interrupted:
        logger.info("Ответ в чате %s прерван: %s", message.chat.id, interrupted)
    return buffer.strip()


async def _answer_plain(message: Message, client: LLMClient, context: list[dict[str, str]]) -> str:
    async with ChatActionSender(bot=message.bot, chat_id=message.chat.id, action=ChatAction.TYPING):
        answer = await client.complete(context)

    parts = split_message(answer)
    if not parts:
        raise LLMError("Сервис вернул пустой ответ. Попробуйте переформулировать вопрос.")
    for part in parts:
        await message.reply(part)
    return answer


def build_router(settings: Settings, client: LLMClient, history: ChatHistory) -> Router:
    """Собирает роутер с зависимостями (удобно тестировать и подменять)."""
    router = Router(name="chat")

    async def answer(message: Message, prompt: str) -> None:
        chat_id = message.chat.id
        await history.append(chat_id, ROLE_USER, prompt)
        context = await history.context(chat_id)
        try:
            if settings.stream:
                reply = await _answer_streaming(message, client, context)
            else:
                reply = await _answer_plain(message, client, context)
        except LLMError as exc:
            # Диалог не состоялся — не оставляем «висящий» вопрос в контексте.
            await history.drop_last(chat_id)
            await message.reply(f"⚠️ {exc}")
            return
        await history.append(chat_id, ROLE_ASSISTANT, reply)

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await message.answer(
            f"Привет, {mention(message.from_user)}! 👋\n\n"
            f"Я бот-ассистент на модели <code>{html.escape(settings.model)}</code>.\n"
            "Напиши вопрос — и я отвечу. Справка: /help",
            parse_mode="HTML",
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("reset"))
    async def cmd_reset(message: Message) -> None:
        removed = await history.reset(message.chat.id)
        if removed:
            await message.answer("🧹 Контекст очищен. Начинаем с чистого листа.")
        else:
            await message.answer("Контекст и так пустой — можно задавать вопрос.")

    @router.message(Command("model"))
    async def cmd_model(message: Message) -> None:
        await message.answer(
            f"Модель: <code>{html.escape(settings.model)}</code>\n"
            f"Провайдер: <code>{html.escape(settings.base_url)}</code>\n"
            f"Температура: {settings.temperature}\n"
            f"Память диалога: {history.limit} сообщений\n"
            f"Стриминг: {'включён' if settings.stream else 'выключен'}",
            parse_mode="HTML",
        )

    @router.message(Command("stats"))
    async def cmd_stats(message: Message) -> None:
        if not settings.is_admin(message.from_user.id if message.from_user else None):
            await message.answer("Команда доступна только администратору бота.")
            return
        await message.answer(f"Активных диалогов в памяти: {history.chats}")

    @router.message(F.text.startswith("/"))
    async def cmd_unknown(message: Message) -> None:
        await message.answer("Не знаю такую команду. Список команд: /help")

    @router.message(F.text)
    async def handle_text(message: Message) -> None:
        if message.from_user and message.from_user.is_bot:
            return
        prompt = _clean(message.text or "")
        if not prompt:
            return
        await answer(message, prompt)

    @router.message()
    async def handle_other(message: Message) -> None:
        await message.reply(
            "Пока я понимаю только текст: голосовые, фото и файлы — не моя сильная сторона."
        )

    return router
