# 🤖 Telegram-бот с ИИ

Бот-ассистент на **aiogram 3** и **Python 3.11+**, который отвечает на сообщения через
любой **OpenAI-совместимый API**: OpenAI, OpenRouter, Groq, Together, Ollama, LM Studio и т. д.

![CI](https://github.com/StaS-a11ylo/-/actions/workflows/ci.yml/badge.svg)

## Возможности

- 💬 **Ответы от LLM** — обычный текст в чат превращается в диалог с моделью.
- ⌨️ **Стриминг** — ответ «печатается» на месте по мере генерации (можно выключить).
- 🧠 **Память диалога** — бот помнит последние сообщения в каждом чате, `/reset` очищает контекст.
- 🛡 **Надёжность** — ретраи с бэкоффом на 429/5xx, таймауты, лимит параллельных запросов.
- 🧩 **Понятные ошибки** — вместо стектрейса пользователь видит «проверьте API_KEY» и т. п.
- ✂️ **Длинные ответы** — автоматическая разбивка на части под лимит Telegram (4096 символов).
- 🐳 **Docker и CI** — готовый образ, `docker compose`, GitHub Actions с тестами.
- ✅ **72 теста** — конфиг, память, клиент LLM на поддельном HTTP-транспорте и бот целиком.

## Быстрый старт

### 1. Получите токен бота

Напишите [@BotFather](https://t.me/BotFather) → `/newbot` → скопируйте токен вида
`123456789:AA...`.

### 2. Возьмите ключ LLM-провайдера

Подойдёт любой сервис с OpenAI-совместимым API (см. таблицу ниже). Если модели
крутятся локально (Ollama), ключ не нужен — положите в `API_KEY` любую непустую строку.

### 3. Установите и запустите

```bash
git clone https://github.com/StaS-a11ylo/-.git
cd ./-
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # заполните BOT_TOKEN, API_KEY, MODEL
python bot.py
```

Или через make:

```bash
make install   # venv + зависимости для разработки
make run       # запуск бота
```

## Провайдеры LLM

| Сервис | `BASE_URL` | Пример `MODEL` |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Together | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Ollama (локально) | `http://127.0.0.1:11434/v1` | `llama3.1` |
| LM Studio (локально) | `http://127.0.0.1:1234/v1` | `local-model` |

Пример `.env` для OpenRouter:

```dotenv
BOT_TOKEN=123456789:AA...
API_KEY=sk-or-v1-...
BASE_URL=https://openrouter.ai/api/v1
MODEL=openai/gpt-4o-mini
```

Пример `.env` для локальной Ollama:

```bash
ollama pull llama3.1
ollama serve
```

```dotenv
BOT_TOKEN=123456789:AA...
API_KEY=ollama
BASE_URL=http://127.0.0.1:11434/v1
MODEL=llama3.1
```

## Команды бота

| Команда | Что делает |
| --- | --- |
| `/start` | Приветствие и подсказка, как начать |
| `/help` | Справка по возможностям |
| `/reset` | Забыть контекст текущего диалога |
| `/model` | Какая модель, провайдер, температура и память используются |
| `/stats` | Сколько диалогов в памяти (только для ID из `ADMIN_IDS`) |

Всё остальное текстовое сообщение уходит в модель как вопрос.

## Настройки

Все параметры задаются переменными окружения (в `.env` или в системе).

| Переменная | По умолчанию | Описание |
| --- | --- | --- |
| `BOT_TOKEN` | — | **Обязательно.** Токен от @BotFather |
| `API_KEY` | — | **Обязательно.** Ключ LLM-провайдера |
| `BASE_URL` | `https://api.openai.com/v1` | Адрес API провайдера |
| `MODEL` | `gpt-4o-mini` | Название модели |
| `SYSTEM_PROMPT` | дружелюбный ассистент | Характер и правила бота |
| `TEMPERATURE` | `0.7` | «Креативность» от 0 до 2 |
| `MAX_TOKENS` | `1024` | Максимум токенов в ответе |
| `REQUEST_TIMEOUT` | `60` | Таймаут запроса к LLM, секунды |
| `MAX_RETRIES` | `2` | Повторы при 429/5xx и сетевых сбоях |
| `HISTORY_LIMIT` | `20` | Сколько последних сообщений помнить в чате |
| `MAX_CHATS` | `1000` | Сколько диалогов держать в памяти |
| `MAX_CONCURRENCY` | `4` | Одновременных запросов к LLM |
| `STREAM` | `true` | Печатать ответ по мере генерации |
| `TELEGRAM_API_BASE` | пусто | Адрес своего Bot API server вместо `api.telegram.org` |
| `ADMIN_IDS` | пусто | Telegram ID админов через запятую |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Docker

```bash
cp .env.example .env    # заполнить
docker compose up -d --build
docker compose logs -f
```

Или без compose:

```bash
docker build -t telegram-ai-bot .
docker run -d --name telegram-ai-bot --env-file .env --restart unless-stopped telegram-ai-bot
```

## Диагностика: проверка провайдера без Telegram

Если бот отвечает ошибкой, проверьте связку «ключ + адрес + модель» отдельным запросом:

```bash
make check-llm                        # или: python scripts/check_llm.py
python scripts/check_llm.py "Сколько будет 2+2?"
```

Скрипт читает тот же `.env`, печатает провайдера и модель, стримит ответ и возвращает
код `0` при успехе, `1` при ошибке запроса, `2` при ошибке конфигурации.

## Разработка

```bash
make lint    # ruff check
make test    # pytest
make check   # линтер + тесты (как в CI)
make format  # автоформат
```

Тесты используют `httpx.MockTransport` для LLM и поддельную сессию Telegram,
поэтому не требуют ни сети, ни реального токена.

## Структура проекта

```
.
├── app/
│   ├── ai.py           # клиент LLM: чат, стриминг, ретраи, разбор ошибок
│   ├── config.py       # настройки из окружения с проверками
│   ├── handlers.py     # команды и обработка сообщений
│   ├── history.py      # память диалога по чатам
│   ├── utils.py        # разбивка длинных сообщений и мелочи
│   └── main.py         # точка входа, логирование, polling
├── scripts/
│   └── check_llm.py    # проверка провайдера без Telegram
├── tests/              # pytest: конфиг, история, LLM-клиент, бот
├── bot.py              # ярлык: python bot.py
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── .github/workflows/ci.yml
```

## Частые проблемы

**`Ошибка конфигурации: Не задана обязательная переменная BOT_TOKEN`**
Не создан `.env` или он лежит не рядом с проектом. Скопируйте `.env.example` в `.env`.

**`Сервис ответил ошибкой 401 — проверьте API_KEY`**
Ключ неверный, истёк или от другого провайдера. Проверьте, что `BASE_URL` и `API_KEY`
относятся к одному сервису.

**`Сервис ответил ошибкой 404 — проверьте BASE_URL и название модели`**
Чаще всего опечатка в `MODEL` или лишний/недостающий `/v1` в `BASE_URL`.

**`Сервис ответил ошибкой 429`**
Исчерпана квота или слишком много запросов. Бот сам повторит попытку несколько раз;
если не помогает — уменьшите `MAX_CONCURRENCY`.

**Бот молчит**
Проверьте логи: `LOG_LEVEL=DEBUG`. Если пришло `TelegramUnauthorizedError` — токен
отозван или скопирован с ошибкой.

## Лицензия

Проект без лицензии: используйте на своё усмотрение.
