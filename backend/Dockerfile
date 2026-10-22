FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && useradd --create-home --uid 10001 rag \
    && mkdir -p /data/uploads /data/models \
    && chown -R rag:rag /data /app
COPY --chown=rag:rag rag ./rag
ENV PATH="/app/.venv/bin:$PATH" DATA_DIR=/data
USER 10001
EXPOSE 8000
CMD ["uvicorn", "rag.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
