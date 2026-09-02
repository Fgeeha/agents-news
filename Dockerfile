FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY config.yaml litellm.config.yaml ./
COPY certs ./certs
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["agents-news"]
