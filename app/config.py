"""Конфигурация бота.

Все значения читаются из переменных окружения (или файла ``.env``).
Явный разбор с понятными ошибками — так проще запускать бота и в Docker,
и локально, и в systemd, без «магии» в коде.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — дружелюбный ассистент в Telegram. Отвечай на языке собеседника, "
    "кратко и по делу, без лишних вступлений. Если не уверен в ответе — "
    "честно скажи об этом."
)

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "да"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "нет"}


class ConfigError(RuntimeError):
    """Конфигурация неполная или содержит некорректные значения."""


def _raw(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _text(env: Mapping[str, str], name: str, *, default: str | None = None) -> str | None:
    return _raw(env, name) or default


def _required(env: Mapping[str, str], name: str) -> str:
    value = _raw(env, name)
    if value is None:
        raise ConfigError(
            f"Не задана обязательная переменная {name}. "
            f"Скопируйте .env.example в .env и заполните значения."
        )
    return value


def _number(env: Mapping[str, str], name: str, *, default: float, cast, minimum=None, maximum=None):
    raw = _raw(env, name)
    if raw is None:
        value = default
    else:
        try:
            value = cast(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} должен быть числом, получено: {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} должен быть не меньше {minimum}, получено {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} должен быть не больше {maximum}, получено {value}")
    return value


def _boolean(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = _raw(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(f"{name} должен быть true/false (или 1/0), получено: {raw!r}")


def _ids(env: Mapping[str, str], name: str) -> frozenset[int]:
    raw = _raw(env, name)
    if raw is None:
        return frozenset()
    result: set[int] = set()
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"{name}: {chunk!r} не похоже на Telegram ID") from exc
    return frozenset(result)


@dataclass(frozen=True, slots=True)
class Settings:
    """Настройки приложения.

    ``bot_token`` может быть пустым: он нужен только самому боту, а не, например,
    скрипту проверки LLM-провайдера. Обязательность проверяет ``app.main``.
    """

    api_key: str
    bot_token: str = ""
    base_url: str = DEFAULT_BASE_URL
    telegram_api_base: str | None = None
    model: str = DEFAULT_MODEL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.7
    max_tokens: int = 1024
    request_timeout: float = 60.0
    max_retries: int = 2
    history_limit: int = 20
    max_chats: int = 1000
    max_concurrency: int = 4
    stream: bool = True
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    log_level: str = "INFO"

    @property
    def endpoint(self) -> str:
        """URL эндпоинта chat completions."""
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, dotenv: bool = True) -> Settings:
        """Собирает настройки из окружения.

        ``env`` удобно передавать в тестах; по умолчанию используется ``os.environ``
        с предварительной подгрузкой ``.env``.
        """
        if env is None:
            if dotenv:
                load_dotenv(ENV_FILE, override=False)
            env = os.environ

        return cls(
            bot_token=_text(env, "BOT_TOKEN", default="") or "",
            api_key=_required(env, "API_KEY"),
            # Свой Bot API server (например, локальный): http://127.0.0.1:8081
            telegram_api_base=_text(env, "TELEGRAM_API_BASE"),
            base_url=_text(env, "BASE_URL", default=DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            model=_text(env, "MODEL", default=DEFAULT_MODEL) or DEFAULT_MODEL,
            system_prompt=_text(env, "SYSTEM_PROMPT", default=DEFAULT_SYSTEM_PROMPT)
            or DEFAULT_SYSTEM_PROMPT,
            temperature=_number(
                env, "TEMPERATURE", default=0.7, cast=float, minimum=0.0, maximum=2.0
            ),
            max_tokens=_number(env, "MAX_TOKENS", default=1024, cast=int, minimum=1),
            request_timeout=_number(env, "REQUEST_TIMEOUT", default=60.0, cast=float, minimum=1.0),
            max_retries=_number(env, "MAX_RETRIES", default=2, cast=int, minimum=0, maximum=10),
            history_limit=_number(env, "HISTORY_LIMIT", default=20, cast=int, minimum=0),
            max_chats=_number(env, "MAX_CHATS", default=1000, cast=int, minimum=1),
            max_concurrency=_number(env, "MAX_CONCURRENCY", default=4, cast=int, minimum=1),
            stream=_boolean(env, "STREAM", default=True),
            admin_ids=_ids(env, "ADMIN_IDS"),
            log_level=(_text(env, "LOG_LEVEL", default="INFO") or "INFO").upper(),
        )
