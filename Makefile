# Единая точка входа для всех операций проекта.
# Зависимости ставятся только через uv — не pip и не poetry.

.DEFAULT_GOAL := help
IMAGE ?= agents-news
CONTAINER ?= agents-news-web

.PHONY: help install gateway run run-once web lint format test check \
        image run-image run-image-web up-local down-local clean

help: ## Показать список целей
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Разработка -------------------------------------------------------------

install: ## Установить зависимости
	uv sync

gateway: ## Запустить шлюз LiteLLM (порт 4000, поверх Ollama)
	uvx --from 'litellm[proxy]' --with 'fastapi==0.115.12' litellm --config litellm.config.yaml --port 4000

run: ## Обработать новые новости из RSS-лент
	uv run agents-news

run-once: ## Пробный запуск: одна новость, без учёта состояния
	uv run agents-news --limit 1 --no-state

web: ## Web-интерфейс: новость с разных углов + рецензент (PORT, по умолчанию 8080)
	uv run agents-news-web

lint: ## Проверить код (ruff check)
	uvx ruff check src tests

format: ## Отформатировать код и починить импорты
	uvx ruff check --fix src tests
	uvx ruff format src tests

test: ## Прогнать тесты (офлайн, без сети и моделей)
	uv run pytest

check: lint test ## Линт и тесты разом

# --- Docker -----------------------------------------------------------------

image: ## Собрать Docker-образ agents-news
	docker build -t $(IMAGE) .

run-image: ## Запустить пайплайн в контейнере (шлюз и Ollama — на хосте)
	docker run --rm --network host \
	  -v $(CURDIR)/config.yaml:/app/config.yaml:ro \
	  -v $(CURDIR)/state:/app/state \
	  -v $(CURDIR)/out:/app/out \
	  $(IMAGE)

run-image-web: ## Запустить web-интерфейс в контейнере на :8080
	docker run --rm --network host \
	  -v $(CURDIR)/config.yaml:/app/config.yaml:ro \
	  --entrypoint agents-news-web $(IMAGE)

up-local: image ## Собрать и запустить web-интерфейс в фоне на :8080
	docker run -d --name $(CONTAINER) --network host \
	  -v $(CURDIR)/config.yaml:/app/config.yaml:ro \
	  --entrypoint agents-news-web $(IMAGE)

down-local: ## Остановить и удалить локальный web-контейнер
	-docker stop $(CONTAINER)
	-docker rm $(CONTAINER)

# --- Прочее -----------------------------------------------------------------

clean: ## Удалить результаты, состояние, кэши и временные артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf out state .pytest_cache .ruff_cache .coverage htmlcov
