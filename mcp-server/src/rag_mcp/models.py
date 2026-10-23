from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class Source(Output):
    id: UUID
    document_id: UUID
    name: str = Field(max_length=200)
    page: int | None
    content: str
    score: float


class SearchResult(Output):
    query: str
    sources: list[Source] = Field(max_length=12)
    count: int
    limit: int
    score_type: Literal["rrf"]
    embedding_model: str


class Document(Output):
    id: UUID
    name: str = Field(max_length=200)
    size_bytes: int
    status: Literal["queued", "processing", "ready", "error"]
    chunk_count: int
    created_at: str
    updated_at: str | None = None
    extension: str | None = None
    ingestion_ms: float | None = None
    extracted_characters: int | None = None
    total_pages: int | None = None
    text_pages: int | None = None


class DocumentPage(Output):
    documents: list[Document] = Field(max_length=100)
    total: int
    page: int
    page_size: int


class Chunk(Output):
    id: UUID
    ordinal: int
    page: int | None
    content: str
    token_count: int | None
    char_count: int


class ChunkPage(Output):
    items: list[Chunk] = Field(max_length=50)
    total: int
    page: int
    page_size: int


class DocumentChunks(Output):
    document: Document
    chunks: ChunkPage


class ComponentStatus(Output):
    status: str
    name: str | None = None
    version: str | None = None


class RagStatus(Output):
    status: str
    database: ComponentStatus
    model: ComponentStatus
    embedding: ComponentStatus
    worker: ComponentStatus
    limits: dict[str, int]
    cpu_threads: int


class LibrarySummary(Output):
    documents: dict[str, int]
    storage_bytes: int
    chunks: int
    formats: list[dict[str, Any]] = Field(max_length=4)
    largest_documents: list[dict[str, Any]] = Field(max_length=8)
    indexing: dict[str, Any]


class Performance(Output):
    window: dict[str, Any]
    models: list[str] = Field(max_length=500)
    chat: dict[str, Any]
    ingestion: dict[str, Any]
    recent_chat: list[dict[str, Any]] = Field(max_length=20)
    recent_ingestion: list[dict[str, Any]] = Field(max_length=20)
