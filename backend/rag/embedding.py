import math

from fastembed import TextEmbedding
from tokenizers import Tokenizer

from rag.config import Settings
from rag.extraction import Page, token_chunks


def vector_literal(vector) -> str:
    values = [float(item) for item in vector]
    if len(values) != 384 or not all(math.isfinite(value) for value in values):
        raise ValueError("Embedding inválido: são necessárias 384 dimensões finitas.")
    return "[" + ",".join(format(value, ".8g") for value in values) + "]"


class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model: TextEmbedding | None = None
        self.tokenizer = None
        self.status = "loading"
        self.error: str | None = None

    def load(self) -> None:
        # The index schema and chunk budget are deliberately fixed to this small model.
        expected = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        if self.settings.embedding_model != expected:
            raise ValueError("Esta versão suporta apenas o MiniLM multilingual de 384 dimensões.")
        self.model = TextEmbedding(
            model_name=expected,
            cache_dir=str(self.settings.models_dir),
            threads=self.settings.cpu_threads,
            providers=["CPUExecutionProvider"],
        )
        # Copy without truncation/padding only for splitting; inference retains model settings.
        self.tokenizer = Tokenizer.from_str(self.model.model.tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.status = "ready"
        self.error = None

    def documents(self, pages: list[Page]) -> list[dict]:
        chunks = token_chunks(
            pages,
            self.tokenizer,
            size=self.settings.chunk_tokens,
            overlap=self.settings.chunk_overlap,
            max_chunks=self.settings.max_chunks_per_document,
        )
        # MiniLM is symmetric: no query:/passage: prefixes. Batch small to bound CPU RAM.
        vectors = self.model.embed(
            [chunk["content"] for chunk in chunks], batch_size=self.settings.embedding_batch_size
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk["embedding"] = vector_literal(vector)
        return chunks

    def query(self, text: str) -> str:
        # Questions can be longer than the embedding window; truncation is explicit.
        encoding = self.tokenizer.encode(text, add_special_tokens=False)
        if len(encoding.ids) > 110:
            text = text[: encoding.offsets[109][1]]
        return vector_literal(next(self.model.embed([text], batch_size=1)))
