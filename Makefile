.DEFAULT_GOAL := help
PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: help install run check-llm test lint format check clean docker-build docker-run

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Создать venv и поставить зависимости для разработки
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt

run: ## Запустить бота
	$(BIN)/python bot.py

check-llm: ## Проверить API_KEY/BASE_URL/MODEL без запуска бота
	$(BIN)/python scripts/check_llm.py

test: ## Запустить тесты
	$(BIN)/python -m pytest

lint: ## Проверить код линтером
	$(BIN)/ruff check .

format: ## Отформатировать код
	$(BIN)/ruff format .
	$(BIN)/ruff check . --fix

check: lint test ## Линтер + тесты (то же, что делает CI)

clean: ## Удалить кэши
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

docker-build: ## Собрать Docker-образ
	docker build -t telegram-ai-bot .

docker-run: ## Запустить бота в Docker
	docker compose up -d --build
