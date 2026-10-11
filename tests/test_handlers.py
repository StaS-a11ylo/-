"""Интеграционные тесты бота: реальный Dispatcher + поддельная сессия Telegram."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import DeleteMessage, EditMessageText, SendMessage
from aiogram.types import PhotoSize, Update

from app.ai import LLMError
from app.config import Settings
from app.handlers import CUT_NOTE, PLACEHOLDER, build_router
from app.history import ChatHistory

from .conftest import CHAT_ID, USER_ID, FakeSession, make_message, make_user

update_ids = itertools.count(1)


class FakeLLM:
    """Поддельный LLM-клиент: отдаёт заранее заданный ответ или ошибку."""

    def __init__(
        self,
        *,
        answer: str = "Ответ модели",
        chunks: list[str] | None = None,
        error: LLMError | None = None,
        error_after: int | None = None,
    ) -> None:
        self.answer = answer
        self.chunks = chunks
        self.error = error
        self.error_after = error_after
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.answer

    async def stream(self, messages) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        for index, chunk in enumerate(self.chunks if self.chunks is not None else [self.answer]):
            if self.error is not None and index == self.error_after:
                raise self.error
            yield chunk
        if self.error is not None:
            raise self.error


class Harness:
    """Бот + диспетчер + поддельная сессия + LLM, собранные для одного теста."""

    def __init__(self, settings: Settings, llm: FakeLLM) -> None:
        self.settings = settings
        self.llm = llm
        self.session = FakeSession()
        self.bot = Bot(token="42:TEST-TOKEN", session=self.session)
        self.dispatcher = Dispatcher()
        self.history = ChatHistory(
            settings.system_prompt, settings.history_limit, settings.max_chats
        )
        self.dispatcher.include_router(build_router(settings, llm, self.history))

    async def send(self, text: str | None = None, *, message=None, chat_id: int = CHAT_ID) -> None:
        message = message or make_message(text, chat_id=chat_id)
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=next(update_ids), message=message)
        )

    @property
    def visible_texts(self) -> list[str]:
        """Все тексты, которые увидел пользователь, в порядке отправки."""
        texts = []
        for method in self.session.requests:
            if isinstance(method, (SendMessage, EditMessageText)) and method.text:
                texts.append(method.text)
        return [text for text in texts if text != PLACEHOLDER]


@pytest.fixture
async def harness(env: dict[str, str]) -> AsyncIterator[Callable[..., Harness]]:
    """Фабрика: harness(settings_env={...}, answer=..., error=...) -> Harness."""
    created: list[Harness] = []

    def factory(*, settings_env: dict[str, str] | None = None, **llm_kwargs) -> Harness:
        settings = Settings.from_env({**env, **(settings_env or {})})
        instance = Harness(settings, FakeLLM(**llm_kwargs))
        created.append(instance)
        return instance

    yield factory

    for instance in created:
        await instance.bot.session.close()


async def test_start_greets_user_with_model(harness) -> None:
    h = harness()

    await h.send("/start")

    reply = h.session.sent_texts[-1]
    assert "Тест" in reply
    assert f"<code>{h.settings.model}</code>" in reply


async def test_help_lists_commands(harness) -> None:
    h = harness()

    await h.send("/help")

    reply = h.session.sent_texts[-1]
    for command in ("/reset", "/model", "/help"):
        assert command in reply


async def test_plain_question_gets_streamed_answer(harness) -> None:
    h = harness()

    await h.send("Как дела?")

    assert h.session.sent_texts[0] == PLACEHOLDER
    assert h.session.last_text == "Ответ модели"
    assert h.llm.calls[0][0]["role"] == "system"
    assert h.llm.calls[0][-1] == {"role": "user", "content": "Как дела?"}


async def test_non_streaming_mode_sends_answer_directly(harness) -> None:
    h = harness(settings_env={"STREAM": "false"})

    await h.send("Привет")

    assert h.session.sent_texts == ["Ответ модели"]
    assert h.llm.calls


async def test_long_answer_is_split_into_parts(harness) -> None:
    answer = " ".join(["предложение"] * 500)
    h = harness(answer=answer)

    await h.send("Расскажи много")

    delivered = h.visible_texts
    assert len(delivered) > 1
    assert all(len(text) <= 4096 for text in delivered)
    assert "".join(delivered).replace(" ", "") == answer.replace(" ", "")


async def test_llm_error_is_reported_and_question_forgotten(harness) -> None:
    h = harness(error=LLMError("Сервис недоступен"), error_after=0)

    await h.send("Вопрос")

    assert h.session.last_text == "⚠️ Сервис недоступен"
    assert await h.history.context(CHAT_ID) == [
        {"role": "system", "content": h.settings.system_prompt}
    ]


async def test_error_after_partial_answer_marks_truncation(harness) -> None:
    h = harness(chunks=["Первая часть ответа"], error=LLMError("обрыв"), error_after=1)

    await h.send("Вопрос")

    assert CUT_NOTE in (h.session.last_text or "")


async def test_placeholder_is_removed_when_nothing_streamed(harness) -> None:
    h = harness(error=LLMError("Сразу ошибка"), error_after=0)

    await h.send("Вопрос")

    assert any(isinstance(m, DeleteMessage) for m in h.session.requests)
    assert h.session.last_text == "⚠️ Сразу ошибка"


async def test_dialog_context_is_kept_between_messages(harness) -> None:
    h = harness(answer="Понял")

    await h.send("Меня зовут Стас")
    await h.send("Как меня зовут?")

    second_call = h.llm.calls[1]
    assert {"role": "user", "content": "Меня зовут Стас"} in second_call
    assert {"role": "assistant", "content": "Понял"} in second_call


async def test_reset_clears_context(harness) -> None:
    h = harness()

    await h.send("Что-то важное")
    await h.send("/reset")
    await h.send("Новый вопрос")

    assert "Контекст очищен" in h.session.sent_texts[-2]
    last_call = h.llm.calls[-1]
    assert len(last_call) == 2  # system + новый вопрос
    assert last_call[-1] == {"role": "user", "content": "Новый вопрос"}


async def test_model_command_shows_settings(harness) -> None:
    h = harness()

    await h.send("/model")

    reply = h.session.sent_texts[-1]
    assert h.settings.model in reply
    assert str(h.settings.temperature) in reply


async def test_unknown_command_gets_hint(harness) -> None:
    h = harness()

    await h.send("/неведомая")

    assert "Не знаю такую команду" in (h.session.last_text or "")
    assert h.llm.calls == []


async def test_stats_requires_admin(harness) -> None:
    h = harness()

    await h.send("/stats")

    assert h.session.last_text == "Команда доступна только администратору бота."


async def test_stats_available_for_admin(harness) -> None:
    h = harness(settings_env={"ADMIN_IDS": str(USER_ID)})

    await h.send("/stats")

    assert "Активных диалогов" in (h.session.last_text or "")


async def test_non_text_message_gets_explanation(harness) -> None:
    h = harness()
    photo = make_message(
        None, photo=[PhotoSize(file_id="f", file_unique_id="u", width=10, height=10)]
    )

    await h.send(message=photo)

    assert "только текст" in (h.session.last_text or "")
    assert h.llm.calls == []


async def test_messages_from_bots_are_ignored(harness) -> None:
    h = harness()
    message = make_message("привет от бота", from_user=make_user(is_bot=True))

    await h.send(message=message)

    assert h.llm.calls == []
    assert h.session.requests == []
