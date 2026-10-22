from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://rag_app:rag_local@localhost:5432/mini_rag"
    data_dir: Path = Path("./data")
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b-q4_K_M"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    cpu_threads: int = Field(default=4, ge=1, le=128)
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    max_documents: int = Field(default=200, ge=1, le=10000)
    max_chunks_per_document: int = Field(default=2000, ge=1, le=10000)
    retrieval_top_k: int = Field(default=6, ge=1, le=12)
    min_similarity: float = Field(default=0.3, ge=0, le=1)
    # One CPU budget for both ingestion and generation. No GPU execution provider.
    generation_timeout_seconds: int = Field(default=300, ge=10, le=1800)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"
