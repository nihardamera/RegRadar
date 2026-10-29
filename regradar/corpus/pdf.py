"""Reading a circular's PDF: text in reading order, tables as Markdown, scanned
pages detected, and a second extractor to catch text the first one dropped.

How a silent drop is caught: pypdf reads the same text layer with different
code. If PyMuPDF's output (tables included) is missing more than a few
percent of the distinct words pypdf finds on a page, the page is flagged.
Distinct words, not a word count: some RBI PDFs hold a page's text twice in
overlapping layers, so both readers see every word twice, and the output
that keeps one copy is the right one. Not word pairs either: the readers
order tables and columns differently. The check the other way (word
counts, so repeats show) finds text this code repeats. Neither reader sees
text that exists only as pixels, which is what the scanned-page check is for.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pymupdf
from pypdf import PdfReader

# A page with less text than this and an image over most of it is a scan.
SCANNED_MAX_CHARS = 40
SCANNED_MIN_IMAGE_SHARE = 0.5
# Word recall against pypdf below this flags the page (text dropped)...
PAGE_RECALL_FLOOR = 0.95
# ...and word precision below this flags it too (text repeated, as when the
# table finder splits a merged cell and its text comes out twice).
PAGE_PRECISION_FLOOR = 0.95
# A table cell this well covered by the table's other cells is a copy.
_REDUNDANT_CELL = 0.9
# A text block inside a table is dropped only if the table holds this share of its words.
_BLOCK_IN_TABLE = 0.8

_WORD = re.compile(r"\w+", re.UNICODE)
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
# Private-use code points and U+FFFD are what broken font encodings turn into.
_GARBLED = re.compile(r"[\uE000-\uF8FF\uFFFD]")


class UnreadablePdf(ValueError):
    """The bytes are not a PDF that can be opened."""


@dataclass
class PageText:
    number: int  # 1-based
    text: str
    tables: int
    scanned: bool
    image_share: float
    reference_recall: float  # share of pypdf's distinct words found in `text`
    reference_precision: float = 1.0  # share of `text`'s words that pypdf also finds


@dataclass
class ParsedPdf:
    pages: list[PageText] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)

    @property
    def scanned_pages(self) -> list[int]:
        return [page.number for page in self.pages if page.scanned]

    @property
    def is_scanned(self) -> bool:
        return bool(self.pages) and len(self.scanned_pages) * 2 >= len(self.pages)

    @property
    def low_recall_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.reference_recall < PAGE_RECALL_FLOOR]

    @property
    def repeated_text_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.reference_precision < PAGE_PRECISION_FLOOR]

    @property
    def table_count(self) -> int:
        return sum(page.tables for page in self.pages)

    def share(self, pattern: re.Pattern[str]) -> float:
        text = self.text
        letters = sum(1 for ch in text if not ch.isspace())
        return len(pattern.findall(text)) / letters if letters else 0.0

    @property
    def devanagari_share(self) -> float:
        return self.share(_DEVANAGARI)

    @property
    def garbled_share(self) -> float:
        return self.share(_GARBLED)


def words(text: str) -> Counter[str]:
    return Counter(_WORD.findall(text.lower()))


def distinct_recall(found: str, reference: str) -> float:
    """Share of `reference`'s distinct words that also occur in `found`.

    Blind to reading order (the two readers order tables and columns
    differently) and to text the reference holds twice; a dropped passage
    still loses its numbers, names and terms. pypdf splits some words
    ("payin g", "cha rges"), so a fragment counts as found when it occurs in
    `found` with its spaces removed. 1.0 when the reference has none.
    """
    want = set(words(reference))
    if not want:
        return 1.0
    have = set(words(found))
    joined = "".join(_WORD.findall(found.lower()))
    return sum(1 for word in want if word in have or word in joined) / len(want)


def repeat_free_share(found: str, reference: str) -> float:
    """Share of `found`'s words that are not extra copies, judged against
    `reference` on the words both hold.

    A word `found` has more often than `reference` is a repeat (a table cell
    read twice). Words `reference` lacks altogether are left out: those are
    the second reader's split words, not repeats. 1.0 when nothing is shared.
    """
    have, want = words(found), words(reference)
    shared = {word: count for word, count in have.items() if word in want}
    total = sum(shared.values())
    return sum(min(count, want[word]) for word, count in shared.items()) / total if total else 1.0


def word_recall(found: str, reference: str) -> float:
    """Share of `reference`'s words (with multiplicity) that also occur in `found`."""
    want = words(reference)
    total = sum(want.values())
    if not total:
        return 1.0
    have = words(found)
    return sum(min(count, have[word]) for word, count in want.items()) / total


def _cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().replace("|", "\\|") if value is not None else ""


def _copies_a_run(rows: list[list[str]], r: int, c: int) -> bool:
    """Whether cell (r, c) holds the same text as the other columns of the rows
    from r down, read row by row, until they hold as many words as it does.

    The copy can step across columns (a paragraph continues down column 1,
    then column 2), so every column but c is read. Column c itself is not,
    so near-identical cells stacked in one column never count as copies.
    """
    text = rows[r][c]
    size = sum(words(text).values())
    run: list[str] = []
    for row in rows[r:]:
        run.extend(value for c2, value in enumerate(row) if c2 != c and value)
        if sum(words(" ".join(run)).values()) >= size:
            break
    joined = " ".join(run)
    return (
        word_recall(joined, text) >= _REDUNDANT_CELL
        and word_recall(text, joined) >= _REDUNDANT_CELL
    )


def drop_repeated_cells(rows: list[list[str]]) -> list[list[str]]:
    """Blank cells that repeat a run of cells in another column.

    PyMuPDF sometimes returns a merged cell's whole paragraph in one cell and
    the same text again line by line down the next column. Only that shape
    counts as a copy: a cell matching, both ways, a run of cells in another
    column that starts on its row. Similar rows in the same column (the
    near-identical titles in a list of repealed circulars) are never compared.
    Cells under 8 words are left alone.

    Cells are judged longest first against the table as it stands, so of two
    copies only one goes: when two columns hold the same text, blanking both
    (each "a copy of the other") would lose it.
    """
    grid = [list(row) for row in rows]
    cells = [(r, c) for r, row in enumerate(grid) for c, value in enumerate(row) if value]
    for r, c in sorted(cells, key=lambda rc: len(grid[rc[0]][rc[1]]), reverse=True):
        if sum(words(grid[r][c]).values()) >= 8 and _copies_a_run(grid, r, c):
            grid[r][c] = ""
    return grid


def table_markdown(rows: list[list[object]]) -> str:
    """A table as Markdown, the first row as its header."""
    cleaned = drop_repeated_cells([[_cell(value) for value in row] for row in rows])
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    if all(sum(1 for value in row if value) <= 1 for row in cleaned):
        # A bordered box of prose (some Master Directions are laid out this
        # way), not a table: one line per row reads and retrieves better.
        return "\n".join(next(value for value in row if value) for row in cleaned)
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    lines = ["| " + " | ".join(cleaned[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in cleaned[1:]]
    return "\n".join(lines)


def _inside(
    block: tuple[float, float, float, float], box: tuple[float, float, float, float]
) -> bool:
    """Whether most of `block` lies within `box`."""
    x0, y0, x1, y1 = block
    bx0, by0, bx1, by1 = box
    width = max(0.0, min(x1, bx1) - max(x0, bx0))
    height = max(0.0, min(y1, by1) - max(y0, by0))
    area = (x1 - x0) * (y1 - y0)
    return area > 0 and width * height / area > 0.6


# PyMuPDF's type hints are partial, so its objects are typed Any here.
def _image_share(page: Any) -> float:
    page_area = page.rect.width * page.rect.height
    if not page_area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return float(min(1.0, covered / page_area))


def _page_text(page: Any) -> tuple[str, int]:
    """The page's text blocks and tables, top to bottom; tables replace the
    text blocks they contain, so table text appears once.

    A block inside a table is dropped only when the table's Markdown holds
    its words. The table finder sometimes draws a table over most of a page
    and returns only some of its text; the rest is then kept as plain text
    rather than lost.
    """
    items: list[tuple[float, float, str]] = []
    boxes: list[tuple[float, float, float, float]] = []
    tables: list[str] = []
    try:
        found = page.find_tables()
    except Exception:  # PyMuPDF's table finder fails on some malformed pages
        found = None
    for table in found.tables if found else []:
        rows = table.extract()
        if len(rows) < 2 or max(len(row) for row in rows) < 2:
            continue
        markdown = table_markdown(rows)
        if markdown:
            box = tuple(table.bbox)
            boxes.append(box)
            tables.append(markdown)
            items.append((box[1], box[0], markdown))
    for x0, y0, x1, y1, text, _number, kind in page.get_text("blocks"):
        if kind != 0 or not text.strip():
            continue
        if any(
            _inside((x0, y0, x1, y1), box) and word_recall(markdown, text) >= _BLOCK_IN_TABLE
            for box, markdown in zip(boxes, tables, strict=True)
        ):
            continue
        items.append((y0, x0, text.strip()))
    items.sort(key=lambda item: (round(item[0], 1), item[1]))
    return "\n".join(text for _y, _x, text in items), len(boxes)


def parse_pdf(data: bytes) -> ParsedPdf:
    # PyMuPDF "repairs" anything into a PDF, even an HTML challenge page saved
    # with a .PDF name, and returns an empty page. The header must be there
    # (the spec allows it within the first 1024 bytes).
    if b"%PDF-" not in data[:1024]:
        raise UnreadablePdf(f"not a PDF; it starts with {data[:40]!r}")
    try:
        document: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception as error:
        raise UnreadablePdf(f"PyMuPDF cannot open it: {error}") from error
    if document.needs_pass:
        raise UnreadablePdf("the PDF is password-protected")
    try:
        reference_pages = [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]
    except Exception:  # pypdf rejects some files PyMuPDF repairs; then there is no cross-check
        reference_pages = []
    parsed = ParsedPdf()
    with document:
        for index, page in enumerate(document):
            text, tables = _page_text(page)
            share = _image_share(page)
            letters = sum(1 for ch in text if not ch.isspace())
            reference = reference_pages[index] if index < len(reference_pages) else ""
            parsed.pages.append(
                PageText(
                    number=index + 1,
                    text=text,
                    tables=tables,
                    scanned=letters < SCANNED_MAX_CHARS and share >= SCANNED_MIN_IMAGE_SHARE,
                    image_share=round(share, 3),
                    reference_recall=round(distinct_recall(text, reference), 4),
                    reference_precision=round(repeat_free_share(text, reference), 4)
                    if reference.strip()
                    else 1.0,
                )
            )
    return parsed
