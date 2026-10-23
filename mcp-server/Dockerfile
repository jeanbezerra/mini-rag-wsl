FROM ghcr.io/astral-sh/uv:0.13.0 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 MCP_HOST=0.0.0.0 MCP_PORT=8001
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 --create-home mcp
USER mcp
EXPOSE 8001
CMD [".venv/bin/python", "-m", "rag_mcp"]
