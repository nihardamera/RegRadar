"""The golden set: hand-written questions whose answers are character ranges.

    uv run python -m regradar.golden sample            # circulars to write about
    uv run python -m regradar.golden find "penal charges" [--doc rbi-n12527]
    uv run python -m regradar.golden add               # write one question
    uv run python -m regradar.golden check             # validate, and progress

A gold answer is a phrase quoted from a corpus document. The tool finds it in
the cleaned text (ignoring whitespace differences) and stores its character
range, so the same answers score every chunking strategy. `find` is plain
keyword search on purpose: locating answers with RegRadar's own retriever
would bias the set toward what that retriever already finds.

Each question's dev/test split is fixed when it is written, from a hash of
its ID, so no question can drift into dev after a test result is seen.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from regradar.chunking import CleanDocument, load_corpus, section_chunks

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden" / "questions.jsonl"

QuestionType = Literal["single_hop", "multi_hop", "number_or_date", "identifier", "unanswerable"]
TYPES: tuple[str, ...] = ("single_hop", "multi_hop", "number_or_date", "identifier", "unanswerable")
TARGETS = {
    "single_hop": 50,
    "multi_hop": 25,
    "number_or_date": 30,
    "identifier": 15,
    "unanswerable": 30,
}
_STOP = frozenset(
    "a an and are as at be by can do does for from has have how if in is it its "
    "may must of on or shall should that the their there this to under what when "
    "where which who whom why will with within".split()
)


class Span(BaseModel):
    doc_id: str
    start: int
    end: int
    quote: str  # as written in the document, for checking the range still holds


class Part(BaseModel):
    """One thing the answer needs. Any of its spans will do: the same rule is
    often restated (a 2023 circular, then the 2025 consolidated Directions)."""

    spans: list[Span] = Field(min_length=1)
    label: str = ""


class Question(BaseModel):
    id: str = Field(pattern=r"^q\d{3}$")
    question: str = Field(min_length=10)
    type: QuestionType
    answer: str = Field(min_length=1)  # the reference answer, in the author's words
    gold: list[Part] = Field(default_factory=list)  # all parts needed
    split: Literal["dev", "test"]
    notes: str = ""
    # Who drafted it. Questions drafted by a model say so; a human review is
    # recorded separately, so the card can state exactly what was checked.
    author: str = "Nihar Damera"
    written: date
    reviewed_by: str = ""
    reviewed: date | None = None

    @field_validator("question", "answer")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def gold_matches_type(self) -> Question:
        if self.type == "unanswerable" and self.gold:
            raise ValueError("an unanswerable question has no gold spans")
        if self.type != "unanswerable" and not self.gold:
            raise ValueError("an answerable question needs at least one gold span")
        if self.type == "multi_hop" and len(self.gold) < 2:
            raise ValueError("a multi-hop question needs at least two parts")
        return self

    @property
    def spans(self) -> list[Span]:
        return [span for part in self.gold for span in part.spans]

    @property
    def answerable(self) -> bool:
        return self.type != "unanswerable"


def split_for(question_id: str) -> Literal["dev", "test"]:
    """Fixed by the ID alone: about a third dev, the rest test."""
    bucket = int(hashlib.sha256(f"regradar-golden:{question_id}".encode()).hexdigest(), 16) % 3
    return "dev" if bucket == 0 else "test"


# --- finding quotes in the cleaned text ---------------------------------------


@dataclass(frozen=True)
class Normalised:
    """Text with each run of whitespace collapsed to one space, and the
    position in the original text of every character kept."""

    text: str
    origin: list[int]

    @classmethod
    def of(cls, raw: str) -> Normalised:
        chars: list[str] = []
        origin: list[int] = []
        in_space = False
        for i, ch in enumerate(raw):
            if ch.isspace():
                if not in_space and chars:
                    chars.append(" ")
                    origin.append(i)
                in_space = True
                continue
            in_space = False
            chars.append(ch)
            origin.append(i)
        return cls("".join(chars), origin)


def _squash(text: str) -> str:
    return " ".join(text.split())


class QuoteNotFound(ValueError):
    pass


def locate(doc: CleanDocument, quote: str, occurrence: int | None = None) -> Span:
    """The character range of `quote` in `doc`, whitespace-insensitive.

    Refuses a quote that is missing, or that occurs more than once unless
    `occurrence` (1-based) says which.
    """
    wanted = _squash(quote)
    if len(wanted.split()) < 3:
        raise QuoteNotFound("quote at least three words, so the range is unambiguous")
    norm = Normalised.of(doc.text)
    hits = [m.start() for m in re.finditer(re.escape(wanted), norm.text)]
    if not hits:
        lowered = norm.text.lower()
        hits = [m.start() for m in re.finditer(re.escape(wanted.lower()), lowered)]
    if not hits:
        raise QuoteNotFound(f"not found in {doc.doc_id}: {wanted[:80]!r}")
    if len(hits) > 1 and occurrence is None:
        raise QuoteNotFound(
            f"{len(hits)} matches in {doc.doc_id}; quote more words or pass the occurrence"
        )
    at = hits[(occurrence or 1) - 1]
    start = norm.origin[at]
    end = norm.origin[at + len(wanted) - 1] + 1
    return Span(doc_id=doc.doc_id, start=start, end=end, quote=doc.text[start:end])


def restatements(docs: dict[str, CleanDocument], span: Span) -> list[Span]:
    """The same words in other documents: candidate alternatives for a part.
    Exact text match, not the retriever, so the set stays independent of it."""
    found: list[Span] = []
    for doc_id, doc in docs.items():
        if doc_id == span.doc_id:
            continue
        try:
            found.append(locate(doc, span.quote, occurrence=1))
        except QuoteNotFound:
            continue
    return found


@cache
def corpus() -> dict[str, CleanDocument]:
    return {doc.doc_id: doc for doc in load_corpus()}


def span_holds(span: Span, docs: dict[str, CleanDocument]) -> bool:
    """The stored range still holds the stored quote (the cleaner has not moved it)."""
    doc = docs.get(span.doc_id)
    return doc is not None and doc.text[span.start : span.end] == span.quote


# --- the file -----------------------------------------------------------------


def load(path: Path = GOLDEN) -> list[Question]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Question.model_validate_json(line) for line in lines if line.strip()]


def save(questions: Sequence[Question], path: Path = GOLDEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [q.model_dump_json() for q in sorted(questions, key=lambda q: q.id)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def next_id(questions: Sequence[Question]) -> str:
    numbers = [int(q.id[1:]) for q in questions]
    return f"q{(max(numbers) + 1) if numbers else 1:03d}"


def overlap(question: str, quotes: Sequence[str]) -> float:
    """Share of the question's content words that appear in its gold quotes.
    High means it was written in the circular's own words, which favours BM25."""
    words = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in _STOP}
    if not words:
        return 0.0
    text = " ".join(quotes).lower()
    return sum(1 for w in words if w in text) / len(words)


@dataclass
class Report:
    problems: list[str]
    authors: Counter[str]
    reviewed: int
    by_type: Counter[str]
    by_split: Counter[str]
    documents: int
    mean_overlap: float


def check(questions: Sequence[Question], docs: dict[str, CleanDocument]) -> Report:
    problems: list[str] = []
    ids = [q.id for q in questions]
    for duplicate in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"{duplicate}: duplicate ID")
    seen: dict[str, str] = {}
    for q in questions:
        if q.split != split_for(q.id):
            problems.append(f"{q.id}: split is {q.split}, but its ID fixes {split_for(q.id)}")
        key = _squash(q.question.lower())
        if key in seen:
            problems.append(f"{q.id}: same question as {seen[key]}")
        seen[key] = q.id
        for span in q.spans:
            if not span_holds(span, docs):
                problems.append(f"{q.id}: span in {span.doc_id} no longer matches its quote")
    answerable = [q for q in questions if q.answerable]
    overlaps = [overlap(q.question, [s.quote for s in q.spans]) for q in answerable]
    return Report(
        problems=problems,
        authors=Counter(q.author for q in questions),
        reviewed=sum(1 for q in questions if q.reviewed_by),
        by_type=Counter(q.type for q in questions),
        by_split=Counter(q.split for q in questions),
        documents=len({s.doc_id for q in questions for s in q.spans}),
        mean_overlap=sum(overlaps) / len(overlaps) if overlaps else 0.0,
    )


# --- command line -------------------------------------------------------------


def where(doc: CleanDocument, span: Span) -> str:
    """Page and section path of a span, to tell repeated wordings apart."""
    section = next((c.section for c in section_chunks(doc) if c.start <= span.start < c.end), None)
    page = doc.page_at(span.start)
    return ", ".join(p for p in (f"page {page}" if page else "", section or "") if p) or "-"


def _context(doc: CleanDocument, span: Span, width: int = 160) -> str:
    before = _squash(doc.text[max(0, span.start - width) : span.start])
    after = _squash(doc.text[span.end : span.end + width])
    return f"…{before} [[{_squash(span.quote)}]] {after}…"


def cmd_sample(args: argparse.Namespace) -> int:
    """Circulars to write about, favouring those no question uses yet, so the
    set is not built from the documents its author already knows."""
    docs = corpus()
    used = Counter(s.doc_id for q in load() for s in q.spans)
    rng = random.Random(args.seed)
    order = sorted(docs, key=lambda d: (used[d], rng.random()))
    for doc_id in order[: args.n]:
        doc = docs[doc_id]
        sections = [c for c in section_chunks(doc) if c.words >= 60]
        excerpt = rng.choice(sections).text if sections else doc.text[:900]
        print(f"\n== {doc_id}  ({used[doc_id]} questions so far)\n   {doc.title}")
        print("   " + _squash(excerpt)[:700])
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """Plain, case-insensitive keyword search: every term must appear in the window."""
    docs = corpus()
    terms = [t.lower() for t in args.terms.split()]
    shown = 0
    for doc_id, doc in docs.items():
        if args.doc and doc_id != args.doc:
            continue
        norm = Normalised.of(doc.text).text
        lowered = norm.lower()
        for match in re.finditer(re.escape(terms[0]), lowered):
            window = lowered[max(0, match.start() - 300) : match.end() + 300]
            if all(t in window for t in terms):
                print(f"{doc_id}  {doc.title[:70]}")
                print(f"   …{norm[max(0, match.start() - 150) : match.end() + 250]}…\n")
                shown += 1
                break
        if shown >= args.limit:
            break
    if not shown:
        print("no matches")
    return 0


def _ask(prompt: str, allowed: Sequence[str] | None = None) -> str:
    while True:
        answer = input(prompt).strip()
        if allowed is None or answer in allowed:
            return answer
        print(f"  one of: {', '.join(allowed)}")


def occurrences(doc: CleanDocument, quote: str) -> list[Span]:
    """Every place `quote` occurs in `doc` (empty when it does not)."""
    found: list[Span] = []
    while True:
        try:
            found.append(locate(doc, quote, occurrence=len(found) + 1))
        except (QuoteNotFound, IndexError):
            return found


def _ask_span(doc: CleanDocument) -> Span | None:
    quote = _ask("  Quote the words that answer it (paste from the document): ")
    try:
        span = locate(doc, quote)
    except QuoteNotFound as error:
        if "matches" not in str(error):
            print(f"  {error}")
            return None
        options = occurrences(doc, quote)
        print(f"  It occurs {len(options)} times in {doc.doc_id}:")
        for n, option in enumerate(options, 1):
            print(f"   {n}. [{where(doc, option)}] {_context(doc, option, width=90)}")
        pick = _ask(
            "  Which one answers the question? ", [str(n) for n in range(1, len(options) + 1)]
        )
        span = options[int(pick) - 1]
    print("  " + _context(doc, span))
    return span if _ask("  Use this span? (y/n) ", ["y", "n"]) == "y" else None


def cmd_add(_args: argparse.Namespace) -> int:
    questions = load()
    docs = corpus()
    qid = next_id(questions)
    print(
        f"Question {qid} (split: {split_for(qid)}). Write it as a compliance analyst would ask it."
    )
    text = _ask("Question: ")
    kind = _ask(f"Type ({' / '.join(TYPES)}): ", TYPES)
    gold: list[Part] = []
    while kind != "unanswerable":
        need = 2 if kind == "multi_hop" else 1
        label = "next part" if gold else "the answer"
        doc_id = _ask(f"  Document holding {label} (e.g. rbi-n12527; blank when done): ")
        if not doc_id:
            if len(gold) >= need:
                break
            print(f"  at least {need} part(s)")
            continue
        if doc_id not in docs:
            print("  not in the corpus")
            continue
        span = _ask_span(docs[doc_id])
        if span is None:
            continue
        part = [span]
        for other in restatements(docs, span):
            print(
                f"  The same words are in {other.doc_id} [{where(docs[other.doc_id], other)}]:"
                f" {docs[other.doc_id].title[:70]}"
            )
            if _ask("  Accept that as an equally correct answer? (y/n) ", ["y", "n"]) == "y":
                part.append(other)
        gold.append(Part(spans=part))
        if kind != "multi_hop":
            break
    answer = _ask(
        "Reference answer, in your words"
        + (" (why it is not answerable)" if kind == "unanswerable" else "")
        + ": "
    )
    notes = input("Notes (optional): ").strip()
    question = Question(
        id=qid,
        question=text,
        type=kind,  # type: ignore[arg-type]
        answer=answer,
        gold=gold,
        split=split_for(qid),
        notes=notes,
        written=date.today(),
    )
    save([*questions, question])
    print(f"saved {qid}. Run `check` for progress.")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Show each unreviewed question with its gold text; approve, or note a fix."""
    questions = load()
    docs = corpus()
    pending = [q for q in questions if not q.reviewed_by]
    if args.sample:
        pending = random.Random(args.seed).sample(pending, min(args.sample, len(pending)))
    print(
        f"{len(pending)} question(s) to review. a = approve, f = needs a fix, s = skip, q = quit."
    )
    by_id = {q.id: q for q in questions}
    for q in pending:
        print(f"\n{q.id} [{q.type}, {q.split}]  {q.question}\n   answer: {q.answer}")
        for n, part in enumerate(q.gold, 1):
            span = part.spans[0]
            more = f" (+{len(part.spans) - 1} restatement(s))" if len(part.spans) > 1 else ""
            print(f"   part {n}: {span.doc_id} [{where(docs[span.doc_id], span)}]{more}")
            print("     " + _context(docs[span.doc_id], span, width=120))
        if q.notes:
            print(f"   notes: {q.notes}")
        choice = _ask("   > ", ["a", "f", "s", "q"])
        if choice == "q":
            break
        if choice == "s":
            continue
        update: dict[str, object] = {"reviewed_by": args.reviewer, "reviewed": date.today()}
        if choice == "f":
            fix = _ask("   what is wrong? ")
            update = {"notes": f"{q.notes} | FIX ({args.reviewer}): {fix}".strip(" |")}
        by_id[q.id] = q.model_copy(update=update)
        save(list(by_id.values()))
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    questions = load()
    report = check(questions, corpus())
    print(
        f"{len(questions)} questions, from {report.documents} documents;"
        f" splits {dict(report.by_split)}"
    )
    for kind in TYPES:
        print(f"  {kind:<15} {report.by_type[kind]:>3} / {TARGETS[kind]}")
    print(
        f"Question words found in their gold quotes: {report.mean_overlap:.0%} on average"
        " (lower means more paraphrased; a set written in the circulars' words favours BM25)."
    )
    print(f"Drafted by: {dict(report.authors)}; reviewed by a person: {report.reviewed}")
    for problem in report.problems:
        print(f"PROBLEM {problem}")
    return 1 if report.problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    sample = steps.add_parser("sample", help="circulars to write questions about")
    sample.add_argument("-n", type=int, default=5)
    sample.add_argument("--seed", type=int)
    sample.set_defaults(run=cmd_sample)
    find = steps.add_parser("find", help="keyword search, to locate the words that answer")
    find.add_argument("terms")
    find.add_argument("--doc")
    find.add_argument("--limit", type=int, default=8)
    find.set_defaults(run=cmd_find)
    steps.add_parser("add", help="write one question").set_defaults(run=cmd_add)
    steps.add_parser("check", help="validate the set and show progress").set_defaults(run=cmd_check)
    review = steps.add_parser("review", help="approve or flag questions, with their gold text")
    review.add_argument("--reviewer", default="Nihar Damera")
    review.add_argument("--sample", type=int, help="review a random sample of this many")
    review.add_argument("--seed", type=int, default=1)
    review.set_defaults(run=cmd_review)
    args = parser.parse_args(argv)
    try:
        result: int = args.run(args)
    except (EOFError, KeyboardInterrupt):
        print("\nstopped; nothing saved for this question")
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
