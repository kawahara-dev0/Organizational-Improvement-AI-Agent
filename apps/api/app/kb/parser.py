"""Document parsers and chunking strategy.

Supported formats: PDF, Excel (.xlsx/.xls), Word (.docx).
Each file is parsed into raw text pages, then split into overlapping
chunks with source metadata attached.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import openpyxl
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from pypdf import PdfReader

# ── Chunking parameters ───────────────────────────────────────────────────────
CHUNK_SIZE = 800  # characters per chunk
CHUNK_OVERLAP = 100  # overlap between consecutive chunks

# ── KB category marker ────────────────────────────────────────────────────────
# Documents may contain lines like  [[KB:Chapter Name]]  to declare the category
# for all subsequent chunks until the next marker.
# Rules:
#   - Must be a standalone line (nothing else on that line except optional whitespace).
#   - The category name is the text between "[[KB:" and "]]".
#   - Chunks before the first marker receive FRONT_MATTER_CATEGORY.
#   - Marker lines are stripped from chunk content.
# PDF text extraction can insert line breaks inside a long marker name; the
# _normalize_kb_markers() helper collapses those before matching.
KB_MARKER_RE = re.compile(r"^\[\[KB:(.+?)\]\]\s*$", re.MULTILINE)
# Used by the normaliser to locate split markers (content may span lines).
_KB_SPLIT_RE = re.compile(r"\[\[KB:(.*?)\]\]", re.DOTALL)
FRONT_MATTER_CATEGORY = "Front matter"
UNCATEGORIZED_CATEGORY = "Uncategorized"


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


def _normalize_kb_markers(text: str) -> str:
    """Normalise ``[[KB:…]]`` markers that PDF extraction may have distorted.

    Two problems are fixed:
    1. **Split across lines** – PDF renderers sometimes insert line breaks inside
       a long marker name.  The inner whitespace/newlines are collapsed to a
       single space so the full marker ends up on one line.
    2. **Inline with surrounding text** – When the PDF layout does not produce a
       line break before/after the marker, the extraction yields something like
       ``Some text [[KB:Chapter]]Next paragraph``.  This function forces every
       marker onto its own line so that KB_MARKER_RE (which requires the marker
       to be the sole content of a line) can match it.
    """

    def _join(m: re.Match) -> str:
        inner = " ".join(m.group(1).split())
        # Surround with newlines so the marker ends up on its own line even if
        # it was embedded in a paragraph by the PDF extractor.
        return f"\n[[KB:{inner}]]\n"

    result = _KB_SPLIT_RE.sub(_join, text)
    # Collapse runs of 3+ newlines introduced by the substitution above.
    return re.sub(r"\n{3,}", "\n\n", result)


def _parse_pdf(data: bytes) -> list[RawPage]:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = _normalize_kb_markers(page.extract_text() or "")
        if text.strip():
            pages.append(RawPage(text=text, page_number=i))
    return pages


def _para_starts_new_page(para) -> bool:
    """Return True if this paragraph carries an explicit page-break signal.

    Detects two Word mechanisms:
    * ``<w:pageBreakBefore/>`` in paragraph properties  → new page before para
    * ``<w:br w:type="page"/>`` run element             → manual page break run
    """
    pPr = para._element.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None:
        return True
    return any(br.get(qn("w:type")) == "page" for br in para._element.iter(qn("w:br")))


def _parse_docx(data: bytes) -> list[RawPage]:
    """Parse a .docx file into RawPages, splitting on explicit page breaks.

    Word documents use automatic pagination (depends on font/margins), so
    automatic page numbers cannot be determined from the file alone.  However,
    manual page breaks (``<w:br type="page"/>``) and the ``pageBreakBefore``
    paragraph property are stored in the XML and can be used to reconstruct
    page boundaries.

    If no explicit page breaks are found, the entire document is returned as a
    single RawPage with page_number=1 (original behaviour).
    """
    doc = DocxDocument(io.BytesIO(data))
    pages: list[RawPage] = []
    current_lines: list[str] = []
    current_page_no = 1

    for para in doc.paragraphs:
        if _para_starts_new_page(para) and current_lines:
            pages.append(RawPage(text="\n".join(current_lines), page_number=current_page_no))
            current_lines = []
            current_page_no += 1

        if para.text.strip():
            current_lines.append(para.text)

    if current_lines:
        pages.append(RawPage(text="\n".join(current_lines), page_number=current_page_no))

    return pages or [RawPage(text="", page_number=1)]


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


def _split_by_markers(text: str) -> list[tuple[str, str | None]]:
    """Split *text* on ``[[KB:…]]`` marker lines.

    Returns a list of ``(segment_text, category)`` pairs where *category* is:
    - ``None``  — the segment precedes the first marker in this page
                  (caller applies the inherited / Front-matter category).
    - ``str``   — the category name declared by the marker that *precedes*
                  this segment.

    Marker lines are excluded from every returned segment.
    """
    result: list[tuple[str, str | None]] = []
    current_marker: str | None = None
    last_end = 0

    for m in KB_MARKER_RE.finditer(text):
        seg = text[last_end : m.start()]
        if seg.strip():
            result.append((seg, current_marker))
        current_marker = m.group(1).strip()
        last_end = m.end()

    remaining = text[last_end:]
    if remaining.strip():
        result.append((remaining, current_marker))

    return result


def chunk_pages(
    pages: list[RawPage],
    source_file: str,
    category: str = "",  # noqa: ARG001 — superseded by [[KB:…]] markers
) -> list[Chunk]:
    """Parse pages into overlapping chunks with per-chunk category metadata.

    Category assignment rules
    -------------------------
    1. A ``[[KB:Chapter Name]]`` marker line (standalone, any position in the
       text) sets the category for all following chunks until the next marker.
    2. Chunks before the first marker receive ``FRONT_MATTER_CATEGORY``.
    3. The category carries over across page boundaries.
    4. If no markers are found the entire document is categorised as
       ``UNCATEGORIZED_CATEGORY`` (no error is raised).
    5. Marker lines are stripped from chunk content.
    6. The legacy *category* parameter is ignored; use markers instead.
    """
    chunks: list[Chunk] = []
    chunk_index = 0
    current_category: str = FRONT_MATTER_CATEGORY
    marker_seen = False

    for page in pages:
        for seg_text, marker_category in _split_by_markers(page.text):
            # A non-None marker_category means a [[KB:…]] line preceded this
            # segment on this page — update the running category.
            if marker_category is not None:
                current_category = marker_category
                marker_seen = True

            for text in _split_text(seg_text, CHUNK_SIZE, CHUNK_OVERLAP):
                if not text.strip():
                    continue
                chunks.append(
                    Chunk(
                        content=text.strip(),
                        metadata={
                            "source_file": source_file,
                            "page_number": page.page_number,
                            "chunk_index": chunk_index,
                            "category": current_category,
                        },
                    )
                )
                chunk_index += 1

    # Documents with no markers at all are labelled "Uncategorized" rather than
    # "Front matter" (which is reserved for the pre-first-marker region of a
    # document that does have markers).
    if not marker_seen:
        for chunk in chunks:
            chunk.metadata["category"] = UNCATEGORIZED_CATEGORY

    return chunks
