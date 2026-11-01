"""The impact pipeline: a circular's obligations, matched against the company's policies.

    uv run python -m regradar.impact index                  # policy paragraphs -> Qdrant
    uv run python -m regradar.impact run rbi-n12898 --model M [--spend]

Three steps, each checked by code before its output is used:

1. **Obligations.** Each section of the circular goes to the model, which
   lists the obligations in it (the rule, who it applies to, the deadline,
   the paragraph) with a quote copied from the section. An obligation whose
   quote is not in the section, or whose deadline has a number the circular
   does not, is sent back once and then dropped.
2. **Gap matching.** For each obligation the policy paragraphs most like it
   are retrieved (hybrid, as for questions), and the model rates it: met,
   gap, partial, not covered by any policy, or not applicable to the company,
   citing paragraphs ("FC-13 §4.1") and quoting the one it relies on.
   The ratings must cover every obligation, cite only paragraphs it was
   shown, quote them exactly, and agree with themselves (v1's "applies: no"
   but "impact: high" is refused). Failing ratings are sent back once; what
   still fails goes to the review queue, never into the plan.
3. **Action plan.** Built by code, not by the model: one action per gap or
   partial, owned by the cited policy's owner, prioritised by severity, due
   by the obligation's deadline. "No action needed" is said only when there
   are no actions, and only when nothing is left for review.

A model call sits behind `Generate`, as for answers, so the checks are tested
with scripted replies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from regradar.answer import Generate
from regradar.chunking import Chunk, CleanDocument, load_corpus, section_chunks
from regradar.company import PolicySection, load_policies, policy_sections

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "eval" / "impact"
COMPANY_COLLECTION = "regradar_company"
POLICY_K = 4  # policy paragraphs retrieved per obligation
MAX_SHOWN = 10  # policy paragraphs shown per section's obligations
WORKERS = 6

Status = Literal["met", "gap", "partial", "not_covered", "not_applicable"]
Severity = Literal["high", "medium", "low", "none"]
NEEDS_ACTION = ("gap", "partial")

# --- step 1: obligations -------------------------------------------------------

EXTRACT_SYSTEM = """You extract obligations from one section of a Reserve Bank of India circular.

An obligation is a rule that a regulated entity must follow or must not break
("shall", "must", "shall not", "is required to", "will not be permitted").
Not obligations: background, definitions, statements of purpose, things that
are only allowed ("may"), and instructions addressed to the RBI itself.

For each obligation give:
- text: the rule in one plain sentence, keeping its numbers, conditions and exceptions;
- applies_to: the entities it applies to, as the section names them;
- deadline: the date or period by which it applies, as written, or null;
- paragraph: the paragraph number as printed (e.g. "22(d)"), or "" if none is visible;
- quote: 8 to 40 words copied exactly from the section that state the rule.

Reply with JSON only: {"obligations": [...]}. If the section has none, {"obligations": []}.
"""

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "applies_to": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "paragraph": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "applies_to", "deadline", "paragraph", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["obligations"],
    "additionalProperties": False,
}


class Obligation(BaseModel):
    text: str = Field(min_length=1)
    applies_to: str = ""
    deadline: str | None = None
    paragraph: str = ""
    quote: str = Field(min_length=1)
    id: str = ""  # set by code: "<chunk id>#<n>"
    chunk_id: str = ""


def _squash(text: str) -> str:
    text = text.lower().translate(str.maketrans("\u2018\u2019\u201c\u201d\u2013\u2014", "''\"\"--"))
    return " ".join(text.split())


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d+(?:[.,/:-]\d+)*", text)}


def obligation_problems(item: Obligation, section: str, document: str) -> list[str]:
    """Why an extracted obligation cannot be trusted; empty when it can."""
    found = []
    if len(item.quote.split()) < 5:
        found.append("the quote is under five words")
    elif _squash(item.quote) not in _squash(section):
        found.append("the quote is not in the section")
    if item.deadline:
        missing = sorted(_numbers(item.deadline) - _numbers(document))
        if missing:
            found.append(f"the deadline has numbers the circular does not: {', '.join(missing)}")
    return found


def _parse(text: str, model: type[BaseModel]) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return model.model_validate(json.loads(text[start : end + 1]))


class _Obligations(BaseModel):
    obligations: list[Obligation] = Field(default_factory=list)


@dataclass
class Extraction:
    chunk_id: str
    obligations: list[Obligation]
    dropped: list[dict[str, Any]] = field(default_factory=list)  # obligation + its problems
    attempts: int = 1


def extract(chunk: Chunk, doc: CleanDocument, generate: Generate, retries: int = 1) -> Extraction:
    """The section's obligations; those that fail the checks after a retry are dropped."""
    prompt = f"Circular: {doc.title}\nSection {chunk.section or ''}:\n\n{chunk.text}"
    feedback = ""
    items: list[Obligation] = []
    failing: list[tuple[Obligation, list[str]]] = []
    for attempt in range(1, retries + 2):  # noqa: B007 (reported after the loop)
        reply = generate(EXTRACT_SYSTEM, prompt + feedback)
        try:
            items = _parse(reply, _Obligations).obligations
        except (ValueError, ValidationError) as error:
            items, failing = [], []
            feedback = f"\n\nYour reply was not the required JSON ({error}). Reply again."
            continue
        failing = [(o, p) for o in items if (p := obligation_problems(o, chunk.text, doc.text))]
        if not failing:
            break
        listed = "\n".join(f"- {o.text[:80]}: {'; '.join(p)}" for o, p in failing)
        feedback = (
            f"\n\nThese obligations failed checks:\n{listed}\n"
            "Reply again with every obligation, quoting the section exactly."
        )
    bad = {id(o) for o, _ in failing}
    kept = [o for o in items if id(o) not in bad]
    for n, o in enumerate(kept, 1):
        o.id, o.chunk_id = f"{chunk.chunk_id}#{n}", chunk.chunk_id
    dropped = [{**o.model_dump(), "problems": p} for o, p in failing]
    return Extraction(chunk.chunk_id, kept, dropped, attempt)


# --- step 2: gap matching -------------------------------------------------------

MATCH_SYSTEM = """You compare regulatory obligations with a company's policies, for its
compliance team.

The company (synthetic, for evaluation) is described first. Then come obligations
from one RBI circular, each with an ID, and numbered policy paragraphs, each with
a reference like "FC-13 §4.1". Use only this text.

For every obligation give one rating:
- applies: does the obligation apply to FlexiPay or FlexiCredit, given what they are
  (entity type, NBFC layer, size, products)? A rule only for banks, for other NBFC
  layers, or for activities they do not carry on does not apply.
- status:
  - "not_applicable" when applies is false;
  - "met" when a cited paragraph does what the obligation requires;
  - "gap" when a cited paragraph contradicts it or falls short of it (a longer
    deadline, a higher limit, a missing step, a prohibited practice);
  - "partial" when cited paragraphs cover part of it and miss part;
  - "not_covered" when no paragraph shown deals with it.
- policy_refs: the references you rely on (none for not_covered / not_applicable).
- policy_quote: 5 to 30 words copied exactly from the first cited paragraph ("" if none).
- finding: one sentence saying what the policy says against what the rule requires.
- severity: "none" for met, not_covered and not_applicable; otherwise "high" (a
  prohibited practice, a regulatory limit or deadline broken), "medium" (a required
  step or disclosure missing) or "low" (a documentation or wording gap).
- action: for gap and partial, the change to make, in one sentence; otherwise null.

A rule that only permits something ("may") is never a gap. Reply with JSON only:
{"ratings": [{"obligation": "<id>", "applies": true|false, "status": "...",
"policy_refs": [...], "policy_quote": "...", "finding": "...", "severity": "...",
"action": "..."|null}, ...]}
"""

MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "obligation": {"type": "string"},
                    "applies": {"type": "boolean"},
                    "status": {
                        "type": "string",
                        "enum": ["met", "gap", "partial", "not_covered", "not_applicable"],
                    },
                    "policy_refs": {"type": "array", "items": {"type": "string"}},
                    "policy_quote": {"type": "string"},
                    "finding": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low", "none"]},
                    "action": {"type": ["string", "null"]},
                },
                "required": [
                    "obligation",
                    "applies",
                    "status",
                    "policy_refs",
                    "policy_quote",
                    "finding",
                    "severity",
                    "action",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratings"],
    "additionalProperties": False,
}


class Rating(BaseModel):
    obligation: str
    applies: bool
    status: Status
    policy_refs: list[str] = Field(default_factory=list)
    policy_quote: str = ""
    finding: str = ""
    severity: Severity = "none"
    action: str | None = None


class _Ratings(BaseModel):
    ratings: list[Rating] = Field(default_factory=list)


def rating_problems(rating: Rating, shown: dict[str, PolicySection]) -> list[str]:
    """Why a rating cannot be used; empty when it can. Ported and extended from v1."""
    found = []
    unknown = [ref for ref in rating.policy_refs if ref not in shown]
    if unknown:
        found.append(f"cites paragraphs it was not shown: {', '.join(unknown)}")
    if not rating.applies and rating.status != "not_applicable":
        found.append(f"says the rule does not apply but rates it {rating.status}")
    if rating.applies and rating.status == "not_applicable":
        found.append("says the rule applies but rates it not_applicable")
    if rating.status in ("met", *NEEDS_ACTION):
        if not rating.policy_refs:
            found.append(f"rates it {rating.status} without citing a policy paragraph")
        elif not unknown:
            first = shown[rating.policy_refs[0]]
            if len(rating.policy_quote.split()) < 3:
                found.append("gives no quote from the cited paragraph")
            elif _squash(rating.policy_quote) not in _squash(first.text):
                found.append(f"the quote is not in {first.ref}")
    if rating.status in NEEDS_ACTION:
        if rating.severity == "none":
            found.append(f"rates it {rating.status} with severity none")
        if not (rating.action or "").strip():
            found.append(f"rates it {rating.status} but gives no action")
    else:
        if rating.severity != "none":
            found.append(f"rates it {rating.status} yet gives severity {rating.severity}")
        if (rating.action or "").strip():
            found.append(f"rates it {rating.status} yet gives an action")
    return found


def coverage_problems(obligations: Sequence[Obligation], ratings: Sequence[Rating]) -> list[str]:
    """Every obligation rated exactly once, and nothing rated that was not asked about."""
    asked = [o.id for o in obligations]
    counts: dict[str, int] = {}
    for r in ratings:
        counts[r.obligation] = counts.get(r.obligation, 0) + 1
    found = [f"obligation {oid} is not rated" for oid in asked if oid not in counts]
    found += [f"obligation {oid} is rated {n} times" for oid, n in counts.items() if n > 1]
    found += [f"rates {oid}, which it was not asked about" for oid in counts if oid not in asked]
    return found


@dataclass
class Matching:
    chunk_id: str
    ratings: list[Rating]
    unrated: list[dict[str, Any]] = field(default_factory=list)  # obligation id + problems
    shown: list[str] = field(default_factory=list)
    attempts: int = 1


PolicySearch = Callable[[str, int], list[PolicySection]]


def company_profile() -> str:
    profile = next(d for d in load_policies() if d.doc_id == "FP-00")
    return " ".join(line for line in profile.body.splitlines() if not line.startswith(">"))


def match(
    obligations: Sequence[Obligation],
    search: PolicySearch,
    generate: Generate,
    profile: str,
    retries: int = 1,
) -> Matching:
    """Ratings for one section's obligations; what fails twice is left unrated."""
    shown: dict[str, PolicySection] = {}
    for o in obligations:
        for section in search(o.text, POLICY_K):
            if len(shown) < MAX_SHOWN:
                shown.setdefault(section.ref, section)
    listed_obligations = "\n".join(
        f"[{o.id}] {o.text} (applies to: {o.applies_to}; deadline: {o.deadline or 'none'})"
        for o in obligations
    )
    listed_policies = "\n".join(
        f"[{s.ref}] {s.title} > {s.heading} ({s.entity}): {s.text}" for s in shown.values()
    )
    prompt = (
        f"Company:\n{profile}\n\nObligations:\n{listed_obligations}\n\n"
        f"Policy paragraphs:\n{listed_policies or '(none retrieved)'}"
    )
    feedback = ""
    good: dict[str, Rating] = {}
    problems: dict[str, list[str]] = {o.id: ["not rated"] for o in obligations}
    for attempt in range(1, retries + 2):  # noqa: B007 (reported after the loop)
        reply = generate(MATCH_SYSTEM, prompt + feedback)
        try:
            ratings = _parse(reply, _Ratings).ratings
        except (ValueError, ValidationError) as error:
            feedback = f"\n\nYour reply was not the required JSON ({error}). Reply again."
            continue
        # An obligation left out stays "not rated"; a repeat or an ID it was
        # not asked about is ignored (the first rating of each counts).
        seen: set[str] = set()
        for r in ratings:
            if r.obligation not in problems or r.obligation in seen:
                continue
            seen.add(r.obligation)
            issues = rating_problems(r, shown)
            if issues:
                problems[r.obligation] = issues
            else:
                good[r.obligation] = r
                problems.pop(r.obligation)
        if not problems:
            break
        listed = "\n".join(f"- {oid}: {'; '.join(p)}" for oid, p in problems.items())
        feedback = (
            f"\n\nThese ratings were refused:\n{listed}\n"
            "Reply again with a rating for every obligation listed above."
        )
    unrated = [{"obligation": oid, "problems": p} for oid, p in problems.items()]
    ordered = [good[o.id] for o in obligations if o.id in good]
    return Matching(
        obligations[0].chunk_id if obligations else "",
        ordered,
        unrated,
        list(shown),
        attempt,
    )


# --- step 3: the plan, and the report ------------------------------------------

PRIORITY = {"high": "P1", "medium": "P2", "low": "P3"}


@dataclass
class Action:
    obligation: str
    action: str
    owner: str
    priority: str
    deadline: str
    policy_refs: list[str]


@dataclass
class Report:
    doc_id: str
    title: str
    obligations: list[Obligation]
    ratings: list[Rating]
    actions: list[Action]
    review: list[dict[str, Any]]  # dropped obligations, unrated ones
    problems: list[str]
    verdict: str
    model: str = ""


def plan(
    obligations: Sequence[Obligation], ratings: Sequence[Rating], sections: dict[str, PolicySection]
) -> list[Action]:
    by_id = {o.id: o for o in obligations}
    actions = []
    for r in ratings:
        if r.status not in NEEDS_ACTION:
            continue
        o = by_id[r.obligation]
        owner = sections[r.policy_refs[0]].owner if r.policy_refs else "Chief Compliance Officer"
        actions.append(
            Action(
                r.obligation,
                (r.action or "").strip(),
                owner,
                PRIORITY[r.severity],
                o.deadline or "not stated in the circular",
                list(r.policy_refs),
            )
        )
    order = {"P1": 0, "P2": 1, "P3": 2}
    return sorted(actions, key=lambda a: (order[a.priority], a.obligation))


def report_problems(report: Report) -> list[str]:
    """Contradictions across the whole report, found by code (v1's plan checks, extended)."""
    found = coverage_problems(report.obligations, report.ratings)
    # Unrated obligations are expected to be missing from the ratings: they are in review.
    in_review = {item.get("obligation") for item in report.review}
    found = [p for p in found if not (p.endswith("is not rated") and p.split()[1] in in_review)]
    needing = {r.obligation for r in report.ratings if r.status in NEEDS_ACTION}
    acted = [a.obligation for a in report.actions]
    found += [f"gap {oid} has no action" for oid in sorted(needing - set(acted))]
    found += [f"action for {oid}, which is not a gap" for oid in acted if oid not in needing]
    if len(acted) != len(set(acted)):
        found.append("an obligation has more than one action")
    if report.verdict == "no action needed" and (report.actions or report.review):
        found.append("says no action is needed but lists actions or items for review")
    if report.verdict == "action needed" and not report.actions:
        found.append("says action is needed but lists no actions")
    return found


def verdict(actions: Sequence[Action], review: Sequence[dict[str, Any]]) -> str:
    if actions:
        return "action needed"
    return "needs review" if review else "no action needed"


def run(
    doc: CleanDocument,
    extract_with: Generate,
    match_with: Generate,
    search: PolicySearch,
    sections: dict[str, PolicySection],
    model: str = "",
    workers: int = WORKERS,
) -> Report:
    chunks = section_chunks(doc)
    profile = company_profile()
    with ThreadPoolExecutor(workers) as pool:
        extractions = list(pool.map(lambda c: extract(c, doc, extract_with), chunks))
        groups = [e.obligations for e in extractions if e.obligations]
        matchings = list(pool.map(lambda g: match(g, search, match_with, profile), groups))
    obligations = [o for e in extractions for o in e.obligations]
    ratings = [r for m in matchings for r in m.ratings]
    review: list[dict[str, Any]] = [
        {"kind": "dropped obligation", **d} for e in extractions for d in e.dropped
    ]
    review += [{"kind": "unrated obligation", **u} for m in matchings for u in m.unrated]
    actions = plan(obligations, ratings, sections)
    report = Report(
        doc.doc_id,
        doc.title,
        obligations,
        ratings,
        actions,
        review,
        [],
        verdict(actions, review),
        model,
    )
    report.problems = report_problems(report)
    return report


def to_json(report: Report) -> dict[str, Any]:
    return {
        "doc_id": report.doc_id,
        "title": report.title,
        "model": report.model,
        "verdict": report.verdict,
        "problems": report.problems,
        "counts": counts(report),
        "obligations": [o.model_dump() for o in report.obligations],
        "ratings": [r.model_dump() for r in report.ratings],
        "actions": [asdict(a) for a in report.actions],
        "review": report.review,
    }


def counts(report: Report) -> dict[str, int]:
    out = {"obligations": len(report.obligations), "actions": len(report.actions)}
    for r in report.ratings:
        out[r.status] = out.get(r.status, 0) + 1
    out["review"] = len(report.review)
    return out


def markdown(report: Report, source_url: str = "") -> str:
    by_id = {o.id: o for o in report.obligations}
    c = counts(report)
    lines = [
        f"# RegRadar impact report: {report.title}",
        "",
        f"- Circular: `{report.doc_id}`" + (f" ({source_url})" if source_url else ""),
        f"- Model: `{report.model}`; company: FlexiPay India (synthetic)",
        f"- Verdict: **{report.verdict}**",
        f"- Code checks: {'; '.join(report.problems) if report.problems else 'all passed'}",
        f"- {c['obligations']} obligations: "
        + ", ".join(f"{c.get(s, 0)} {s.replace('_', ' ')}" for s in Status.__args__)  # type: ignore[attr-defined]
        + f"; {c['review']} for review",
        "- Status: draft for human review",
        "",
        "## Action plan",
        "",
    ]
    if not report.actions:
        lines.append(
            "No actions." if report.verdict != "needs review" else "No actions yet; see review."
        )
    for n, a in enumerate(report.actions, 1):
        o = by_id[a.obligation]
        lines += [
            f"{n}. **{a.action}**",
            f"   - Priority {a.priority}; owner: {a.owner}; due: {a.deadline}",
            f'   - Rule (¶{o.paragraph or "?"}): "{o.quote}"',
            f"   - Policy: {', '.join(a.policy_refs)}",
        ]
    lines += [
        "",
        "## Findings",
        "",
        "| Obligation | ¶ | Status | Policy | Finding |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.ratings:
        if r.status == "not_applicable":
            continue
        o = by_id[r.obligation]
        lines.append(
            f"| {o.text} | {o.paragraph} | {r.status.replace('_', ' ')}"
            f"{' (' + r.severity + ')' if r.severity != 'none' else ''} | "
            f"{', '.join(r.policy_refs) or '-'} | {r.finding} |"
        )
    na = [r for r in report.ratings if r.status == "not_applicable"]
    if na:
        lines += ["", f"## Not applicable ({len(na)})", ""]
        lines += [f"- {by_id[r.obligation].text}: {r.finding}" for r in na]
    if report.review:
        lines += ["", f"## For human review ({len(report.review)})", ""]
        for item in report.review:
            what = item.get("text") or item.get("obligation")
            lines.append(f"- {item['kind']}: {what}: {'; '.join(item['problems'])}")
    return "\n".join(lines) + "\n"


# --- policy retrieval -----------------------------------------------------------


def index_policies(client: Any) -> int:
    """The policy paragraphs as a Qdrant collection, searched like the corpus."""
    from qdrant_client import models

    from regradar.index import (
        DENSE_MODELS,
        create_collection,
        dense_vectors,
        point_id,
        sparse_vectors,
    )

    sections = policy_sections()
    texts = [f"{s.title} > {s.heading}\n\n{s.text}" for s in sections]
    dense = {model: dense_vectors(model, "company", texts) for model in DENSE_MODELS}
    sparse = sparse_vectors(texts)
    create_collection(client, COMPANY_COLLECTION)
    points = [
        models.PointStruct(
            id=point_id(f"company:{s.ref}"),
            vector={**{m: dense[m][i].tolist() for m in DENSE_MODELS}, "bm25": sparse[i]},
            payload={
                "chunk_id": s.ref,
                "doc_id": s.doc_id,
                "start": 0,
                "end": 0,
                "title": s.title,
                "text": s.text,
            },
        )
        for i, s in enumerate(sections)
    ]
    client.upsert(COMPANY_COLLECTION, points, wait=True)
    return len(points)


def qdrant_policy_search(client: Any, encoders: Any = None) -> PolicySearch:
    from regradar.index import Retriever

    retriever = Retriever(client, "company", encoders=encoders, name=COMPANY_COLLECTION)
    sections = {s.ref: s for s in policy_sections()}

    def search(query: str, k: int) -> list[PolicySection]:
        return [sections[h.chunk_id] for h in retriever.search(query, mode="hybrid", k=k)]

    return search


# --- command line ---------------------------------------------------------------


def cmd_index(_args: argparse.Namespace) -> int:
    from regradar.index import connect

    print(f"{index_policies(connect())} policy paragraphs indexed in {COMPANY_COLLECTION}")
    return 0


def analyse(
    doc_id: str, model: str, spend: bool, client: Any = None, encoders: Any = None
) -> Report:
    from regradar.index import connect
    from regradar.llm import Claude

    doc = next(d for d in load_corpus() if d.doc_id == doc_id)
    extract_with = Claude(model, "impact-extract", spend=spend, schema=EXTRACT_SCHEMA)
    match_with = Claude(model, "impact-match", spend=spend, schema=MATCH_SCHEMA)
    search = qdrant_policy_search(client or connect(), encoders)
    sections = {s.ref: s for s in policy_sections()}
    return run(doc, extract_with, match_with, search, sections, model)


def cmd_run(args: argparse.Namespace) -> int:
    report = analyse(args.doc_id, args.model, args.spend)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = REPORTS / f"{args.doc_id}_{args.model}"
    stem.with_suffix(".json").write_text(
        json.dumps(to_json(report), indent=1) + "\n", encoding="utf-8"
    )
    stem.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(f"{report.verdict}: {counts(report)} -> {stem}.md")
    for p in report.problems:
        print(f"CHECK FAILED: {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("index").set_defaults(run=cmd_index)
    one = steps.add_parser("run")
    one.add_argument("doc_id")
    one.add_argument("--model", required=True, help="there is no default model")
    one.add_argument("--spend", action="store_true")
    one.set_defaults(run=cmd_run)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
