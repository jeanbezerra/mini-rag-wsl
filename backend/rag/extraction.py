import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_TEXT_CHARACTERS = 2_000_000
MAX_PAGES = 500
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class Page:
    text: str
    number: int | None = None


def normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n")
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_pages(path: Path, extension: str) -> list[Page]:
    pages: list[Page] = []
    total = 0

    def append(text: str, number: int | None = None) -> None:
        nonlocal total
        text = normalize(text)
        total += len(text)
        if total > MAX_TEXT_CHARACTERS:
            raise ExtractionError("Texto excede 2 milhões de caracteres. Divida o documento.")
        if text:
            pages.append(Page(text, number))

    try:
        if extension == ".pdf":
            reader = PdfReader(path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ExtractionError("PDF protegido por senha. Envie uma cópia sem proteção.")
            if len(reader.pages) > MAX_PAGES:
                raise ExtractionError("PDF excede 500 páginas. Divida o documento.")
            for index, page in enumerate(reader.pages, 1):
                append(page.extract_text() or "", index)
        elif extension == ".docx":
            with ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
                    raise ExtractionError("DOCX descompactado excede 50 MB.")
            document = Document(path)
            # DOCX has no stable page numbers; include paragraphs and table cell text.
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph):
                    append(block.text)
                elif isinstance(block, Table):
                    for row in block.rows:
                        append(" | ".join(cell.text for cell in row.cells))
            # Combine small paragraphs before splitting to avoid one embedding per line.
            pages = [Page("\n\n".join(page.text for page in pages))] if pages else []
        elif extension in {".txt", ".md"}:
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExtractionError(
                    "TXT e Markdown precisam estar codificados em UTF-8."
                ) from exc
            if "\x00" in text:
                raise ExtractionError("Arquivo binário não é um documento de texto UTF-8.")
            append(text)
        else:
            raise ExtractionError("Formato não suportado.")
    except ExtractionError:
        raise
    except (OSError, ValueError, BadZipFile, KeyError) as exc:
        raise ExtractionError(
            "Não foi possível ler o documento; verifique se está íntegro."
        ) from exc
    if not pages:
        raise ExtractionError(
            "Nenhum texto encontrado. PDFs digitalizados precisam de OCR externo."
        )
    return pages


def token_chunks(
    pages: list[Page], tokenizer, *, size: int = 110, overlap: int = 16, max_chunks: int = 2000
) -> list[dict]:
    """Use model tokenizer offsets, so every chunk fits its 128-token input window.

    Disabling truncation on a private tokenizer copy is essential: the model's tokenizer
    normally truncates at 128 and would otherwise silently discard the end of each page.
    """
    if not 0 <= overlap < size <= 120:
        raise ValueError("Invalid chunk token size/overlap")
    chunks: list[dict] = []
    for page in pages:
        encoding = tokenizer.encode(page.text, add_special_tokens=False)
        offsets = [pair for pair in encoding.offsets if pair[1] > pair[0]]
        start = 0
        while start < len(offsets):
            end = min(start + size, len(offsets))
            content = page.text[offsets[start][0] : offsets[end - 1][1]].strip()
            if content:
                # Retokenization can alter boundary segmentation. Shrink conservatively
                # instead of permitting hidden model truncation.
                while len(tokenizer.encode(content, add_special_tokens=True).ids) > 128:
                    end -= 1
                    content = page.text[offsets[start][0] : offsets[end - 1][1]].strip()
                chunks.append({"content": content, "page": page.number})
                if len(chunks) > max_chunks:
                    raise ExtractionError("Documento gera fragmentos demais. Divida o arquivo.")
            if end >= len(offsets):
                break
            start = max(start + 1, end - overlap)
    return chunks
