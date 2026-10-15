#!/usr/bin/env python3
"""Проверка настройки LLM-провайдера без Telegram.

Читает ``.env`` (или переменные окружения) и делает один запрос к модели —
удобно убедиться, что ``API_KEY``, ``BASE_URL`` и ``MODEL`` верны.

Запуск::

    python scripts/check_llm.py
    python scripts/check_llm.py "Сколько будет 2+2?"
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import LLMClient, LLMError
from app.config import ConfigError, Settings

DEFAULT_PROMPT = "Ответь одним коротким предложением: связь с моделью работает."


async def check(prompt: str) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"❌ Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    print(f"• Провайдер: {settings.base_url}")
    print(f"• Модель:    {settings.model}")
    print(f"• Стриминг:  {'да' if settings.stream else 'нет'}")
    print(f"• Вопрос:    {prompt}\n")

    client = LLMClient(settings)
    started = time.monotonic()
    try:
        if settings.stream:
            print("• Ответ: ", end="", flush=True)
            collected: list[str] = []
            async for chunk in client.stream([{"role": "user", "content": prompt}]):
                collected.append(chunk)
                print(chunk, end="", flush=True)
            print()
            answer = "".join(collected)
        else:
            answer = await client.complete([{"role": "user", "content": prompt}])
            print(f"• Ответ:    {answer}")
    except LLMError as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()

    if not answer.strip():
        print("❌ Модель вернула пустой ответ.", file=sys.stderr)
        return 1

    print(f"\n✅ Всё работает за {time.monotonic() - started:.1f} c.")
    return 0


def main() -> None:
    prompt = " ".join(sys.argv[1:]).strip() or DEFAULT_PROMPT
    raise SystemExit(asyncio.run(check(prompt)))


if __name__ == "__main__":
    main()
