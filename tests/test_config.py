"""Тесты конфигурации."""

from __future__ import annotations

import pytest

from app.config import DEFAULT_BASE_URL, DEFAULT_MODEL, ConfigError, Settings


def test_defaults_applied(env: dict[str, str]) -> None:
    settings = Settings.from_env(env)

    assert settings.bot_token == "42:TEST-TOKEN"
    assert settings.api_key == "sk-test"
    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.model == "test-model"
    assert settings.stream is True
    assert settings.max_retries == 2


def test_endpoint_has_no_double_slash(env: dict[str, str]) -> None:
    settings = Settings.from_env({**env, "BASE_URL": "https://example.com/v1/"})

    assert settings.endpoint == "https://example.com/v1/chat/completions"


def test_model_falls_back_to_default(env: dict[str, str]) -> None:
    settings = Settings.from_env({k: v for k, v in env.items() if k != "MODEL"})

    assert settings.model == DEFAULT_MODEL


def test_missing_api_key_raises(env: dict[str, str]) -> None:
    env = {k: v for k, v in env.items() if k != "API_KEY"}

    with pytest.raises(ConfigError, match="API_KEY"):
        Settings.from_env(env)


def test_blank_api_key_is_treated_as_missing(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="API_KEY"):
        Settings.from_env({**env, "API_KEY": "   "})


def test_bot_token_is_optional_for_library_use(env: dict[str, str]) -> None:
    env = {k: v for k, v in env.items() if k != "BOT_TOKEN"}

    assert Settings.from_env(env).bot_token == ""
    assert Settings.from_env({**env, "BOT_TOKEN": "  "}).bot_token == ""


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TEMPERATURE", "hot"),
        ("MAX_TOKENS", "many"),
        ("TEMPERATURE", "5"),
        ("MAX_RETRIES", "-1"),
        ("MAX_CHATS", "0"),
    ],
)
def test_invalid_numbers_raise(env: dict[str, str], name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({**env, name: value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("YES", True), ("0", False), ("off", False), ("нет", False)],
)
def test_boolean_parsing(env: dict[str, str], value: str, expected: bool) -> None:
    settings = Settings.from_env({**env, "STREAM": value})

    assert settings.stream is expected


def test_invalid_boolean_raises(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="STREAM"):
        Settings.from_env({**env, "STREAM": "может быть"})


def test_admin_ids_parsing(env: dict[str, str]) -> None:
    settings = Settings.from_env({**env, "ADMIN_IDS": "1, 2;3 ,4"})

    assert settings.admin_ids == frozenset({1, 2, 3, 4})
    assert settings.is_admin(2) is True
    assert settings.is_admin(99) is False
    assert settings.is_admin(None) is False


def test_invalid_admin_ids_raise(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="ADMIN_IDS"):
        Settings.from_env({**env, "ADMIN_IDS": "1,abc"})


def test_log_level_is_uppercased(env: dict[str, str]) -> None:
    settings = Settings.from_env({**env, "LOG_LEVEL": "debug"})

    assert settings.log_level == "DEBUG"
