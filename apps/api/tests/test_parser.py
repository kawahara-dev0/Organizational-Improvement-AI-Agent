"""Unit tests for app.kb.parser — KB marker extraction and chunking."""

from __future__ import annotations

from app.kb.parser import (
    FRONT_MATTER_CATEGORY,
    UNCATEGORIZED_CATEGORY,
    RawPage,
    _normalize_kb_markers,
    _split_by_markers,
    chunk_pages,
)

# ── _split_by_markers ──────────────────────────────────────────────────────────


def test_normalize_kb_markers_joins_pdf_split_marker() -> None:
    """PDF extraction may wrap a long marker name across lines."""
    text = "Intro\n[[KB: EMPLOYEE HANDBOOK ACKNOWLEDGMENT\nAND RECEIPT]]\nBody"

    normalized = _normalize_kb_markers(text)

    assert "[[KB:EMPLOYEE HANDBOOK ACKNOWLEDGMENT AND RECEIPT]]" in normalized
    assert "ACKNOWLEDGMENT\nAND RECEIPT" not in normalized


def test_normalize_kb_markers_splits_inline_pdf_marker_to_own_line() -> None:
    """PDF extraction may concatenate a marker with surrounding text."""
    normalized = _normalize_kb_markers("Before[[KB:Employment at Will]]After")

    assert normalized == "Before\n[[KB:Employment at Will]]\nAfter"
    result = _split_by_markers(normalized)
    assert [(seg.strip(), cat) for seg, cat in result] == [
        ("Before", None),
        ("After", "Employment at Will"),
    ]


def test_split_by_markers_no_markers() -> None:
    """Text with no markers → one segment with category None."""
    result = _split_by_markers("Hello world\nSecond line")
    assert len(result) == 1
    text, cat = result[0]
    assert cat is None
    assert "Hello world" in text
    assert "[[KB:" not in text


def test_split_by_markers_single_marker() -> None:
    """One marker divides text into two segments."""
    result = _split_by_markers("Intro text\n[[KB:Chapter One]]\nChapter body")
    assert len(result) == 2

    intro_text, intro_cat = result[0]
    assert intro_cat is None
    assert "Intro text" in intro_text
    assert "[[KB:" not in intro_text

    body_text, body_cat = result[1]
    assert body_cat == "Chapter One"
    assert "Chapter body" in body_text
    assert "[[KB:" not in body_text


def test_split_by_markers_multiple_markers() -> None:
    """Multiple markers produce one segment per section, markers excluded."""
    text = "Cover page\n[[KB:Section A]]\nBody of A\n[[KB:Section B]]\nBody of B\n"
    result = _split_by_markers(text)
    assert len(result) == 3

    cats = [cat for _, cat in result]
    assert cats == [None, "Section A", "Section B"]

    for seg, _ in result:
        assert "[[KB:" not in seg


def test_split_by_markers_marker_at_start() -> None:
    """Marker at start → no leading segment, first returned segment has the category."""
    result = _split_by_markers("[[KB:Chapter One]]\nBody text")
    assert len(result) == 1
    seg, cat = result[0]
    assert cat == "Chapter One"
    assert "Body text" in seg
    assert "[[KB:" not in seg


def test_split_by_markers_marker_not_standalone_is_ignored() -> None:
    """Inline [[KB:…]] that is NOT a standalone line must not be treated as a marker."""
    text = "Some text with [[KB:Fake]] in the middle\nNext line"
    result = _split_by_markers(text)
    assert len(result) == 1
    seg, cat = result[0]
    assert cat is None
    # The inline marker text must remain in the segment (it's not a real marker)
    assert "[[KB:Fake]]" in seg


# ── chunk_pages — marker lines absent from content ────────────────────────────


def _make_page(text: str, page_number: int = 1) -> RawPage:
    return RawPage(text=text, page_number=page_number)


def test_chunk_pages_marker_not_in_content() -> None:
    """No chunk's content should contain a [[KB:…]] marker string."""
    text = (
        "Intro paragraph about the company.\n"
        "[[KB:Employee Privacy]]\n"
        "Privacy policy body text that is long enough to be kept as a chunk. " * 5 + "\n"
        "[[KB:Workweek and Hours of Work]]\n"
        "Hours of work body text. " * 5
    )
    pages = [_make_page(text)]
    chunks = chunk_pages(pages, source_file="handbook.docx")

    for chunk in chunks:
        assert "[[KB:" not in chunk.content, (
            f"Marker leaked into chunk content: {chunk.content[:120]!r}"
        )


def test_chunk_pages_front_matter_category_before_first_marker() -> None:
    """Chunks before the first [[KB:…]] receive the Front matter category."""
    text = "Cover page content.\n[[KB:Chapter One]]\nChapter body."
    chunks = chunk_pages([_make_page(text)], source_file="doc.pdf")

    cover_chunks = [c for c in chunks if "Cover page" in c.content]
    assert cover_chunks, "Expected at least one cover-page chunk"
    for c in cover_chunks:
        assert c.metadata["category"] == FRONT_MATTER_CATEGORY


def test_chunk_pages_category_assigned_after_marker() -> None:
    """Chunks after [[KB:Chapter One]] receive 'Chapter One' as category."""
    text = "Intro\n[[KB:Chapter One]]\n" + "Chapter one body text. " * 20
    chunks = chunk_pages([_make_page(text)], source_file="doc.pdf")

    chapter_chunks = [c for c in chunks if "Chapter one body" in c.content]
    assert chapter_chunks, "Expected at least one chapter chunk"
    for c in chapter_chunks:
        assert c.metadata["category"] == "Chapter One"


def test_chunk_pages_category_inherits_across_pages() -> None:
    """Category set on page 1 must carry over to page 2 with no markers."""
    page1 = _make_page("[[KB:Privacy]]\nPrivacy intro.", page_number=1)
    page2 = _make_page("Continued privacy body text.", page_number=2)
    chunks = chunk_pages([page1, page2], source_file="doc.pdf")

    for c in chunks:
        assert c.metadata["category"] == "Privacy", (
            f"Expected 'Privacy' but got {c.metadata['category']!r} for chunk: {c.content[:60]!r}"
        )


def test_chunk_pages_no_markers_all_uncategorized() -> None:
    """Documents with no [[KB:…]] markers must not raise; all chunks get Uncategorized."""
    text = "Just plain text. " * 30
    chunks = chunk_pages([_make_page(text)], source_file="plain.pdf")

    assert chunks, "Expected at least one chunk"
    for c in chunks:
        assert c.metadata["category"] == UNCATEGORIZED_CATEGORY


def test_chunk_pages_category_changes_mid_document() -> None:
    """Category must switch precisely at each [[KB:…]] marker."""
    text = (
        "[[KB:Section A]]\n" + "Section A text. " * 10 + "\n"
        "[[KB:Section B]]\n" + "Section B text. " * 10
    )
    chunks = chunk_pages([_make_page(text)], source_file="doc.pdf")

    for c in chunks:
        if "Section A text" in c.content:
            assert c.metadata["category"] == "Section A"
        elif "Section B text" in c.content:
            assert c.metadata["category"] == "Section B"
