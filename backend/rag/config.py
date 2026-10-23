from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PublicSettings(BaseModel):
    """Only these settings may be read or changed through the public API."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    ollama_model: str = Field(
        default="qwen3:1.7b-q4_K_M",
        min_length=1,
        max_length=200,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$",
    )
    temperature: float = Field(default=0.15, ge=0, le=2)
    top_p: float = Field(default=0.9, ge=0.05, le=1)
    repeat_penalty: float = Field(default=1.0, ge=0.5, le=2)
    max_output_tokens: int = Field(default=512, ge=128, le=2048)
    context_tokens: int = Field(default=4096, ge=4096, le=16384)
    cpu_threads: int = Field(default=4, ge=1, le=128)
    generation_batch_size: int = Field(default=128, ge=32, le=512)
    keep_alive_minutes: int = Field(default=10, ge=0, le=60)
    generation_timeout_seconds: int = Field(default=300, ge=10, le=1800)
    retrieval_top_k: int = Field(default=6, ge=1, le=12)
    min_similarity: float = Field(default=0.3, ge=0, le=1)
    chunk_tokens: int = Field(default=110, ge=32, le=120)
    chunk_overlap: int = Field(default=16, ge=0, le=32)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    max_upload_mb: int = Field(default=25, ge=1, le=100)
    max_documents: int = Field(default=200, ge=1, le=10000)
    max_pdf_pages: int = Field(default=500, ge=1, le=10000)
    max_text_characters: int = Field(default=2_000_000, ge=10000, le=20_000_000)
    max_docx_uncompressed_mb: int = Field(default=50, ge=1, le=200)
    max_chunks_per_document: int = Field(default=2000, ge=1, le=20000)

    @model_validator(mode="after")
    def compatible_budgets(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("A sobreposição deve ser menor que o tamanho do fragmento.")
        if self.context_tokens < self.max_output_tokens + 2500:
            raise ValueError("O contexto precisa reservar pelo menos 2500 tokens além da resposta.")
        return self


class Settings(PublicSettings, BaseSettings):
    # Environment strings are parsed at startup; the public API uses strict types.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", strict=False, frozen=True)

    database_url: str = "postgresql://rag_app:rag_local@localhost:5432/mini_rag"
    data_dir: Path = Path("./data")
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def public(self) -> PublicSettings:
        return PublicSettings.model_validate(
            self.model_dump(include=PublicSettings.model_fields.keys())
        )

    def with_public(self, values: PublicSettings) -> "Settings":
        return self.model_copy(update=values.model_dump())

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"
