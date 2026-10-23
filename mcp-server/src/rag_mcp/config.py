from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore", frozen=True)

    api_base_url: str = "http://127.0.0.1:8000"
    request_timeout_seconds: float = Field(default=180, ge=5, le=1800)
    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65535)

    @field_validator("api_base_url")
    @classmethod
    def api_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("Use a origem HTTP da API, sem credenciais ou caminho.")
        try:
            _ = url.port
        except ValueError as exc:
            raise ValueError("Porta da API inválida.") from exc
        return value.rstrip("/")
