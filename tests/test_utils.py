"""Тесты утилит: разбиение длинных сообщений и мелочи."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils import TELEGRAM_MESSAGE_LIMIT, mention, split_message, truncate


def test_short_text_is_single_part() -> None:
    assert split_message("привет") == ["привет"]


def test_empty_text_gives_no_parts() -> None:
    assert split_message("") == []


def test_long_text_is_split_within_limit() -> None:
    text = " ".join(["слово"] * 2000)

    parts = split_message(text)

    assert len(parts) > 1
    assert all(len(part) <= TELEGRAM_MESSAGE_LIMIT for part in parts)
    assert "".join(parts).replace(" ", "") == text.replace(" ", "")


def test_splits_prefer_paragraph_boundaries() -> None:
    first = "а" * 30
    second = "б" * 30

    parts = split_message(f"{first}\n\n{second}", limit=40)

    assert parts == [first, second]


def test_split_without_separators_hard_cuts() -> None:
    parts = split_message("x" * 250, limit=100)

    assert [len(part) for part in parts] == [100, 100, 50]


def test_custom_limit_is_respected() -> None:
    parts = split_message("аб вг де", limit=5)

    assert all(len(part) <= 5 for part in parts)
    assert "".join(parts).replace(" ", "") == "абвгде"


@pytest.mark.parametrize("limit", [0, -1])
def test_invalid_limit_raises(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        split_message("текст", limit=limit)


def test_truncate_adds_ellipsis() -> None:
    assert truncate("привет мир", 8) == "привет…"
    assert truncate("коротко", 20) == "коротко"


def test_mention_prefers_first_name() -> None:
    assert mention(SimpleNamespace(first_name="Стас", username="stas")) == "Стас"
    assert mention(SimpleNamespace(first_name=None, username="stas")) == "stas"
    assert mention(None) == "друг"
