"""Cleaning a corpus document and cutting it into chunks, three ways.

    fixed      word windows with overlap, ignoring structure
    recursive  paragraphs, then lines, then sentences, merged up to a size
    section    the circular's own paragraph numbering (1., 2.1, Chapter III,
               Annex 2), with the heading path kept

Every chunk records its character range in the cleaned document text. The
golden set's answers are ranges too, so a chunk is relevant when it overlaps
an answer's range, whichever strategy cut it; chunk IDs are only stable
names within one strategy.

The section strategy also checks the numbering it relies on: a document
whose top-level paragraphs jump (7, then 9) or go back is reported, since a
gap is either text lost in parsing or numbering the chunker misread.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

CHUNK_WORDS = 220  # target size, all strategies, so the ablation compares like with like
FIXED_OVERLAP = 40
SECTION_MAX_WORDS = 350  # a section longer than this is split at its sub-items
SECTION_MIN_WORDS = 25  # a shorter one (a bare heading) joins the next

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_LETTER = re.compile(r"[^\W\d_]")
_BOILERPLATE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^_{3,}\s*RESERVE BANK OF INDIA\s*_{3,}$",
        r"^RESERVE BANK OF INDIA$",
        r"^(https?://)?www\.rbi\.org\.in/?$",
        r"^page \d+ of \d+$",
        r"^-?\s*\d{1,3}\s*-?$",  # a bare page number
        r"^_{5,}$",
        r"(tel(ephone)?\.? no|fax)\s*[:/].{0,40}\d{3}",
        r"central office building|shaheed bhagat singh marg|fort,? mumbai",
    )
]
# A table-of-contents line: dot leaders, then a page number.
_TOC_LINE = re.compile(r"\.{5,}\s*\d{1,4}\s*$")

# Section starts, at the beginning of a line.
_CHAPTER = re.compile(r"^(chapter|part)\s+([IVXLC]+|\d+)\b", re.IGNORECASE)
_ANNEX = re.compile(
    r"^(annex(?:ure)?|appendix|schedule)\s*[-\u2013:]?\s*([IVXLC]+|\d+|[A-Z])?\b", re.I
)
_TOP = re.compile(r"^(\d{1,3})\.\s+\S")  # 1. Introduction
_DOTTED = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){1,3})\.?\s+\S")  # 2.1 / 2.1.3
_SUB = re.compile(r"^(\(?[a-z]{1,4}\)|\(?[ivx]{1,5}\)|[a-z]\.|[ivx]{1,5}\.)\s+\S")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    strategy: str
    text: str
    start: int  # character range in the cleaned document text
    end: int
    page: int | None  # page the chunk starts on (None for HTML-only documents)
    section: str | None = None  # heading path, e.g. "Chapter III > 22", for `section`

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class CleanDocument:
    doc_id: str
    title: str
    text: str
    page_starts: list[tuple[int, int]] = field(default_factory=list)  # (offset, page number)
    dropped_lines: int = 0

    def page_at(self, offset: int) -> int | None:
        page = None
        for start, number in self.page_starts:
            if start > offset:
                break
            page = number
        return page


def _mostly_devanagari(line: str) -> bool:
    letters = _LETTER.findall(line)
    return bool(letters) and sum(1 for ch in letters if _DEVANAGARI.match(ch)) / len(letters) > 0.5


def clean(doc_id: str, title: str, pages: Sequence[tuple[int, str]]) -> CleanDocument:
    """Drop the letterhead, footers, page numbers and table of contents.

    Also drops any line that appears on more than half the pages of a
    document with at least three pages (a running header or footer). Text
    is otherwise kept as parsed; offsets refer to the result.
    """
    split = [(number, [line.strip() for line in text.splitlines()]) for number, text in pages]
    repeated: set[str] = set()
    if len(split) >= 3:
        counts = Counter(line for _n, lines in split for line in set(lines) if line)
        repeated = {line for line, count in counts.items() if count > len(split) / 2}
    out: list[str] = []
    page_starts: list[tuple[int, int]] = []
    offset = 0
    dropped = 0
    for number, lines in split:
        kept = []
        for line in lines:
            if not line:
                continue
            if (
                line in repeated
                or _mostly_devanagari(line)
                or _TOC_LINE.search(line)
                or any(p.search(line) for p in _BOILERPLATE)
            ):
                dropped += 1
                continue
            kept.append(line)
        if not kept:
            continue
        block = "\n".join(kept)
        if out:
            offset += 2  # the "\n\n" between pages
        page_starts.append((offset, number))
        out.append(block)
        offset += len(block)
    return CleanDocument(doc_id, title, "\n\n".join(out), page_starts, dropped)


def _word_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _make(
    doc: CleanDocument, strategy: str, n: int, start: int, end: int, section: str | None
) -> Chunk:
    return Chunk(
        chunk_id=f"{doc.doc_id}:{strategy}:{n:04d}",
        doc_id=doc.doc_id,
        strategy=strategy,
        text=doc.text[start:end],
        start=start,
        end=end,
        page=doc.page_at(start),
        section=section,
    )


def fixed_chunks(
    doc: CleanDocument, size: int = CHUNK_WORDS, overlap: int = FIXED_OVERLAP
) -> list[Chunk]:
    spans = _word_spans(doc.text)
    chunks: list[Chunk] = []
    step = size - overlap
    for n, first in enumerate(range(0, max(1, len(spans) - overlap), step)):
        last = min(first + size, len(spans)) - 1
        if last < first:
            break
        chunks.append(_make(doc, "fixed", n, spans[first][0], spans[last][1], None))
    return chunks


_SEPARATORS = [re.compile(r"\n\s*\n"), re.compile(r"\n"), re.compile(r"(?<=[.;:])\s+")]


def _split_range(
    text: str, start: int, end: int, size: int, level: int = 0
) -> Iterator[tuple[int, int]]:
    """Ranges of at most `size` words, cut at the coarsest separator that works."""
    if len(text[start:end].split()) <= size or level >= len(_SEPARATORS):
        if level >= len(_SEPARATORS) and len(text[start:end].split()) > size:
            spans = [(start + a, start + b) for a, b in _word_spans(text[start:end])]
            for i in range(0, len(spans), size):
                window = spans[i : i + size]
                yield window[0][0], window[-1][1]
            return
        yield start, end
        return
    pieces: list[tuple[int, int]] = []
    cursor = start
    for match in _SEPARATORS[level].finditer(text, start, end):
        if match.start() > cursor:
            pieces.append((cursor, match.start()))
        cursor = match.end()
    if cursor < end:
        pieces.append((cursor, end))
    # Merge neighbours up to `size`; recurse into any piece that is still too big.
    current: tuple[int, int] | None = None
    for piece in pieces:
        if len(text[piece[0] : piece[1]].split()) > size:
            if current:
                yield current
                current = None
            yield from _split_range(text, piece[0], piece[1], size, level + 1)
            continue
        if current and len(text[current[0] : piece[1]].split()) <= size:
            current = (current[0], piece[1])
        else:
            if current:
                yield current
            current = piece
    if current:
        yield current


def recursive_chunks(doc: CleanDocument, size: int = CHUNK_WORDS) -> list[Chunk]:
    ranges = [
        r for r in _split_range(doc.text, 0, len(doc.text), size) if doc.text[r[0] : r[1]].strip()
    ]
    return [_make(doc, "recursive", n, a, b, None) for n, (a, b) in enumerate(ranges)]


@dataclass(frozen=True)
class Heading:
    offset: int  # start of the line
    kind: str  # chapter, annex, top, dotted
    label: str


def _index_like(line: str) -> bool:
    """A short numbered or annex line, as an index lists them."""
    if len(line.split()) > 10:
        return False
    return bool(_TOP.match(line) or _DOTTED.match(line) or _ANNEX.match(line))


def _toc_lines(lines: list[tuple[int, str]]) -> set[int]:
    """Indexes of lines in a table of contents: runs of three or more
    index-like lines (the HTML versions have no dot leaders). The last line of
    a run is a real heading when text follows it, as when the body's
    "1. Introduction" comes straight after the index."""
    content = [i for i, (_o, line) in enumerate(lines) if line]
    toc: set[int] = set()
    run: list[int] = []
    for i in [*content, -1]:
        if i >= 0 and _index_like(lines[i][1]):
            run.append(i)
            continue
        if len(run) >= 3:
            followed_by_text = i >= 0
            toc.update(run[:-1] if followed_by_text else run)
        run = []
    return toc


def headings(text: str) -> list[Heading]:
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        lines.append((offset, line.strip()))
        offset += len(line) + 1
    toc = _toc_lines(lines)
    found: list[Heading] = []
    for i, (start, line) in enumerate(lines):
        if not line or i in toc:
            continue
        if match := _CHAPTER.match(line):
            found.append(Heading(start, "chapter", f"{match.group(1).title()} {match.group(2)}"))
        elif (match := _ANNEX.match(line)) and len(line.split()) <= 12:
            label = match.group(1).title() + (f" {match.group(2)}" if match.group(2) else "")
            found.append(Heading(start, "annex", label))
        elif match := _DOTTED.match(line):
            found.append(Heading(start, "dotted", match.group(1)))
        elif match := _TOP.match(line):
            found.append(Heading(start, "top", match.group(1)))
    return found


@dataclass
class NumberingReport:
    doc_id: str
    top_numbers: int
    problems: list[str]


def numbering_report(doc: CleanDocument) -> NumberingReport:
    """Gaps and reversals in the top-level paragraph numbers, per scope (the
    body, then each annex, which restarts its own numbering)."""
    problems: list[str] = []
    scope, previous, count = "body", 0, 0
    for heading in headings(doc.text):
        if heading.kind == "annex":
            scope, previous = heading.label, 0
            continue
        if heading.kind != "top":
            continue
        number = int(heading.label)
        count += 1
        if previous and number > previous + 1:
            problems.append(f"{scope}: {previous} then {number}")
        elif previous and number <= previous:
            problems.append(f"{scope}: {previous} then {number} (restarts or goes back)")
        previous = number
    return NumberingReport(doc.doc_id, count, problems)


def section_chunks(
    doc: CleanDocument, max_words: int = SECTION_MAX_WORDS, min_words: int = SECTION_MIN_WORDS
) -> list[Chunk]:
    marks = [h for h in headings(doc.text) if h.kind in ("chapter", "annex", "top", "dotted")]
    bounds = [0, *(h.offset for h in marks if h.offset > 0), len(doc.text)]
    paths: list[str | None] = [None]
    chapter = annex = top = None
    for heading in marks:
        if heading.kind == "chapter":
            chapter, annex, top = heading.label, None, None
        elif heading.kind == "annex":
            annex, top = heading.label, None
        elif heading.kind == "top":
            top = heading.label
        parts = [
            p for p in (annex or chapter, heading.label if heading.kind == "dotted" else top) if p
        ]
        if heading.offset > 0:
            paths.append(" > ".join(parts) or None)
        else:
            paths[0] = " > ".join(parts) or None
    sections = [(bounds[i], bounds[i + 1], paths[i]) for i in range(len(bounds) - 1)]

    # A bare heading (or a sliver of text) joins the section after it.
    merged: list[tuple[int, int, str | None]] = []
    carry: tuple[int, str | None] | None = None
    for start, end, path in sections:
        if carry:
            start, path = carry[0], path or carry[1]
            carry = None
        if len(doc.text[start:end].split()) < min_words and end < len(doc.text):
            carry = (start, path)
            continue
        merged.append((start, end, path))
    if carry:
        merged.append((carry[0], len(doc.text), carry[1]))

    chunks: list[Chunk] = []
    for start, end, path in merged:
        if not doc.text[start:end].strip():
            continue
        if len(doc.text[start:end].split()) <= max_words:
            pieces = [(start, end)]
        else:
            pieces = list(_split_by_subitems(doc.text, start, end, max_words))
        for a, b in pieces:
            chunks.append(_make(doc, "section", len(chunks), a, b, path))
    return chunks


def _split_by_subitems(text: str, start: int, end: int, size: int) -> Iterator[tuple[int, int]]:
    """Split a long section at its sub-items ((a), (i), a.), merged up to
    `size` words; anything still too long falls back to the recursive split."""
    cuts = [start]
    offset = start
    for line in text[start:end].split("\n"):
        if offset > start and _SUB.match(line.strip()):
            cuts.append(offset)
        offset += len(line) + 1
    cuts.append(end)
    current: tuple[int, int] | None = None
    for a, b in pairwise(cuts):
        if current and len(text[current[0] : b].split()) <= size:
            current = (current[0], b)
            continue
        if current:
            yield from _split_range(text, current[0], current[1], size)
        current = (a, b)
    if current:
        yield from _split_range(text, current[0], current[1], size)


STRATEGIES = {
    "fixed": fixed_chunks,
    "recursive": recursive_chunks,
    "section": section_chunks,
}
