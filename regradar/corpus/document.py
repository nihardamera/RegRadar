"""Turning a notification page and its PDF into one corpus document.

The PDF is the text of record: it is what RBI signs, and from 2026 the web
page often has no text at all. When the page does carry the circular as
HTML, the two are compared word by word in both directions. That comparison
is the second check (after pypdf's, per page) that parsing dropped nothing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from regradar.corpus import metadata
from regradar.corpus.pdf import ParsedPdf, word_recall

# The HTML body must hold at least this much text to be worth comparing.
MIN_HTML_CHARS = 500
# Below this, the HTML has words the PDF text is missing: a likely drop.
HTML_RECALL_FLOOR = 0.9
# Documents sharing this share of their 5-word shingles are near-copies.
DUPLICATE_JACCARD = 0.8
_HEADER_CHARS = 3000


def doc_id(notification: int) -> str:
    return f"rbi-n{notification}"


def describe(
    page: dict[str, Any],
    html_text: str,
    parsed: ParsedPdf | None,
    pdf_problem: str | None = None,
) -> dict[str, Any]:
    """The manifest row for one circular: metadata, sources and parse checks.

    `status` is `ok`, `scanned` (no usable text layer and no HTML to fall
    back on) or `no_text` (no PDF could be read and no HTML either).
    """
    pdf_text = parsed.text if parsed else ""
    has_html = len(html_text) >= MIN_HTML_CHARS
    usable_pdf = parsed is not None and not parsed.is_scanned and pdf_text.strip() != ""
    if usable_pdf:
        source, status = "pdf", "ok"
    elif has_html:
        source, status = "html", "ok"
    else:
        source = None
        status = "scanned" if parsed is not None and parsed.is_scanned else "no_text"

    header = (html_text if has_html else pdf_text)[:_HEADER_CHARS]
    reference = metadata.reference_number(header)
    number = metadata.circular_number(header)
    published = metadata.first_date(header)
    row: dict[str, Any] = {
        "doc_id": doc_id(page["id"]),
        "notification_id": page["id"],
        "title": page["title"],
        "kind": metadata.document_kind(page["title"]),
        "circular_number": number,
        "reference": reference,
        "department": metadata.department(reference) or metadata.department(number),
        "date": published.isoformat() if published else None,
        "addressees": metadata.addressees(header),
        "regulator": "RBI",
        "page_url": page["page_url"],
        "page_capture_url": page["capture_url"],
        "pdf_url": page.get("pdf_url"),
        "text_source": source,
        "status": status,
        "html_chars": len(html_text),
    }
    if pdf_problem:
        row["pdf_problem"] = pdf_problem
    if parsed is not None:
        row.update(
            {
                "pages": len(parsed.pages),
                "pdf_chars": len(pdf_text),
                "tables": parsed.table_count,
                "scanned_pages": parsed.scanned_pages,
                "low_recall_pages": parsed.low_recall_pages,
                "repeated_text_pages": parsed.repeated_text_pages,
                "min_page_recall": min((p.reference_recall for p in parsed.pages), default=1.0),
                "devanagari_share": round(parsed.devanagari_share, 4),
                "garbled_share": round(parsed.garbled_share, 4),
            }
        )
        if has_html and pdf_text:
            row["html_in_pdf_recall"] = round(word_recall(pdf_text, html_text), 4)
            row["pdf_in_html_recall"] = round(word_recall(html_text, pdf_text), 4)
    return row


def text_of(row: dict[str, Any], html_text: str, parsed: ParsedPdf | None) -> str:
    if row["text_source"] == "pdf" and parsed is not None:
        return parsed.text
    if row["text_source"] == "html":
        return html_text
    return ""


def shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    tokens = re.findall(r"\w+", text.lower())
    return {tuple(tokens[i : i + size]) for i in range(max(0, len(tokens) - size + 1))}


def near_duplicates(
    texts: Sequence[tuple[str, str]], threshold: float = DUPLICATE_JACCARD
) -> dict[str, str]:
    """Map each near-copy's id to the id of the document kept in its place.

    `texts` is (doc_id, text) with the preferred document first (newest), so
    of two near-copies the earlier one in the list is kept.
    """
    kept: list[tuple[str, set[tuple[str, ...]]]] = []
    copies: dict[str, str] = {}
    for identifier, text in texts:
        mine = shingles(text)
        for other, theirs in kept:
            union = len(mine | theirs)
            if union and len(mine & theirs) / union >= threshold:
                copies[identifier] = other
                break
        else:
            kept.append((identifier, mine))
    return copies
