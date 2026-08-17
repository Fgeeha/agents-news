.DEFAULT_GOAL := help
.PHONY: help install gateway run run-once lint format test check image run-image clean

# ---------- Справка ----------

help: ## Показать список целей
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------- Установка ----------

install: ## Установить зависимости через uv
	uv sync

# ---------- Запуск ----------

gateway: ## Запустить шлюз LiteLLM (порт 4000, поверх Ollama)
	uvx --from 'litellm[proxy]' --with 'fastapi==0.115.12' litellm --config litellm.config.yaml --port 4000

run: ## Обработать новые новости из RSS-лент
	uv run agents-news

run-once: ## Пробный запуск: одна новость, без учёта состояния
	uv run agents-news --limit 1 --no-state

# ---------- Проверка ----------

lint: ## Проверить код ruff
	uvx ruff check src tests

format: ## Отформатировать код ruff
	uvx ruff format src tests

test: ## Запустить тесты
	uv run pytest -q

check: lint test ## Линт и тесты разом

# ---------- Docker ----------

image: ## Собрать Docker-образ agents-news
	docker build -t agents-news .

run-image: ## Запустить пайплайн в контейнере (шлюз и Ollama — на хосте)
	docker run --rm --network host \
	  -v $(CURDIR)/config.yaml:/app/config.yaml:ro \
	  -v $(CURDIR)/state:/app/state \
	  -v $(CURDIR)/out:/app/out \
	  agents-news

# ---------- Обслуживание ----------

clean: ## Удалить результаты, состояние и кэши
	rm -rf out state .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
