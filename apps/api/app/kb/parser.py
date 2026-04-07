"""Document parsers and chunking strategy.

Supported formats: PDF, Excel (.xlsx/.xls), Word (.docx).
Each file is parsed into raw text pages, then split into overlapping
chunks with source metadata attached.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import openpyxl
from docx import Document as DocxDocument
from pypdf import PdfReader

# ── Chunking parameters ───────────────────────────────────────────────────────
CHUNK_SIZE = 800      # characters per chunk
CHUNK_OVERLAP = 100   # overlap between consecutive chunks


@dataclass
class RawPage:
    text: str
    page_number: int  # 1-based; sheet index for Excel


@dataclass
class Chunk:
    content: str
    metadata: dict = field(default_factory=dict)
    # metadata keys: source_file, page_number, chunk_index, category


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_pdf(data: bytes) -> list[RawPage]:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(RawPage(text=text, page_number=i))
    return pages


def _parse_docx(data: bytes) -> list[RawPage]:
    doc = DocxDocument(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)
    return [RawPage(text=text, page_number=1)]


def _parse_xlsx(data: bytes) -> list[RawPage]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pages = []
    for sheet_index, sheet in enumerate(wb.worksheets, start=1):
        rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                rows.append("\t".join(cells))
        if rows:
            pages.append(RawPage(text="\n".join(rows), page_number=sheet_index))
    return pages


_PARSERS: dict[str, callable] = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
    "xls": _parse_xlsx,
}


def parse(data: bytes, filename: str) -> list[RawPage]:
    ext = filename.rsplit(".", 1)[-1].lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported file type: .{ext}")
    return parser(data)


# ── Chunking ──────────────────────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def chunk_pages(
    pages: list[RawPage],
    source_file: str,
    category: str = "",
) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_index = 0
    for page in pages:
        for text in _split_text(page.text, CHUNK_SIZE, CHUNK_OVERLAP):
            if not text.strip():
                continue
            chunks.append(
                Chunk(
                    content=text.strip(),
                    metadata={
                        "source_file": source_file,
                        "page_number": page.page_number,
                        "chunk_index": chunk_index,
                        "category": category,
                    },
                )
            )
            chunk_index += 1
    return chunks
