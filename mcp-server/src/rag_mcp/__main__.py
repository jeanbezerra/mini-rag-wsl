import uvicorn

from rag_mcp.app import create_app
from rag_mcp.config import Settings


def main():
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        limit_concurrency=64,
        timeout_graceful_shutdown=10,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
