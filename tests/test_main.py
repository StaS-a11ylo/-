"""Тесты точки входа: коды выхода и понятные сообщения об ошибках."""

from __future__ import annotations

import logging

import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import GetMe

from app import main as app_main
from app.config import ConfigError, Settings

METHOD = GetMe()


@pytest.mark.parametrize(
    ("error", "code", "needle"),
    [
        (ConfigError("Не задана обязательная переменная BOT_TOKEN"), 2, "Ошибка конфигурации"),
        (TelegramUnauthorizedError(method=METHOD, message="Unauthorized"), 2, "BOT_TOKEN"),
        (TelegramNetworkError(method=METHOD, message="нет сети"), 3, "Нет связи с Telegram API"),
    ],
)
def test_run_maps_errors_to_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    error: Exception,
    code: int,
    needle: str,
) -> None:
    async def failing_main() -> None:
        raise error

    monkeypatch.setattr(app_main, "main", failing_main)

    with pytest.raises(SystemExit) as exc_info:
        app_main.run()

    assert exc_info.value.code == code
    assert needle in capsys.readouterr().err


def test_run_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    async def interrupted_main() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app_main, "main", interrupted_main)

    app_main.run()  # не должно поднимать исключение

    assert "Остановлено пользователем" in capsys.readouterr().out


def test_create_bot_uses_default_telegram_api(env: dict[str, str]) -> None:
    bot = app_main.create_bot(Settings.from_env(env))

    assert bot.token == "42:TEST-TOKEN"
    assert "api.telegram.org" in bot.session.api.base


def test_create_bot_supports_local_api_server(env: dict[str, str]) -> None:
    settings = Settings.from_env({**env, "TELEGRAM_API_BASE": "http://127.0.0.1:8081"})

    bot = app_main.create_bot(settings)

    assert bot.session.api.base == "http://127.0.0.1:8081/bot{token}/{method}"


def test_require_bot_token_rejects_empty_value(env: dict[str, str]) -> None:
    settings = Settings.from_env({k: v for k, v in env.items() if k != "BOT_TOKEN"})

    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        app_main.require_bot_token(settings)

    app_main.require_bot_token(Settings.from_env(env))  # с токеном — без исключений


def test_run_reports_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_main() -> None:
        raise RuntimeError("что-то пошло не так")

    monkeypatch.setattr(app_main, "main", broken_main)

    with pytest.raises(SystemExit) as exc_info:
        app_main.run()

    assert exc_info.value.code == 1


def test_setup_logging_configures_root_logger() -> None:
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    try:
        app_main.setup_logging("DEBUG")

        assert root.level == logging.DEBUG
        assert logging.getLogger("aiogram.event").level == logging.WARNING
    finally:
        root.setLevel(saved[0])
        root.handlers[:] = saved[1]
