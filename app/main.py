"""Точка входа: логирование, опрос Telegram и корректное завершение."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import BotCommand

from . import __version__
from .ai import LLMClient
from .config import ConfigError, Settings
from .handlers import build_router
from .history import ChatHistory

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Познакомиться"),
    BotCommand(command="help", description="Что я умею"),
    BotCommand(command="reset", description="Очистить контекст диалога"),
    BotCommand(command="model", description="Какая модель используется"),
]


def setup_logging(level: str) -> None:
    """Настраивает логирование так, как нужно боту (а не сторонней библиотеке)."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # бот владеет процессом: свои обработчики важнее чужих
    )
    # Сторонние библиотеки на уровне INFO логируют каждое обновление — это шумно.
    for noisy in ("aiogram.event", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_bot(settings: Settings) -> Bot:
    """Создаёт Bot: с обычным Telegram API или с локальным Bot API server."""
    session = (
        AiohttpSession(api=TelegramAPIServer.from_base(settings.telegram_api_base))
        if settings.telegram_api_base
        else None
    )
    return Bot(
        settings.bot_token,
        session=session,
        # parse_mode=None: ответы модели отправляем как есть, без риска сломать разметку.
        # Статические сообщения явно просят HTML там, где он нужен.
        default=DefaultBotProperties(parse_mode=None),
    )


def require_bot_token(settings: Settings) -> None:
    """Проверяет то, без чего бот не имеет смысла запускать."""
    if not settings.bot_token:
        raise ConfigError(
            "Не задана обязательная переменная BOT_TOKEN. "
            "Скопируйте .env.example в .env и заполните значения."
        )


async def main(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    require_bot_token(settings)
    setup_logging(settings.log_level)
    logger.info(
        "Запускаю бота v%s | модель=%s | стриминг=%s",
        __version__,
        settings.model,
        settings.stream,
    )

    bot = create_bot(settings)
    dispatcher = Dispatcher()
    client = LLMClient(settings)
    history = ChatHistory(settings.system_prompt, settings.history_limit, settings.max_chats)
    dispatcher.include_router(build_router(settings, client, history))

    try:
        await bot.set_my_commands(BOT_COMMANDS)
        me = await bot.get_me()
        logger.info("Бот @%s готов, слушаю сообщения", me.username)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await client.aclose()
        await bot.session.close()
        logger.info("Бот остановлен")


def run() -> None:
    """Синхронная обёртка для ``python bot.py`` с понятными кодами выхода."""
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except TelegramUnauthorizedError:
        print(
            "Telegram отклонил токен. Проверьте BOT_TOKEN — актуальный токен выдаёт @BotFather.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except TelegramNetworkError as exc:
        print(
            f"Нет связи с Telegram API: {exc}. Проверьте интернет, VPN или прокси.",
            file=sys.stderr,
        )
        raise SystemExit(3) from None
    except KeyboardInterrupt:
        print("Остановлено пользователем")
    except SystemExit:
        raise
    except Exception:  # на верхнем уровне логируем всё, что угодно
        logger.exception("Бот упал с ошибкой")
        raise SystemExit(1) from None
