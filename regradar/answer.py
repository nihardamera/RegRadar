"""Answers that must cite the chunks they come from, checked by code.

The model gets the question and the retrieved chunks and must reply with JSON:
claims, each citing the chunk IDs it rests on, or "not found". Code then
decides whether the answer stands, as v1's code checks overruled its
verifier agent:

    - the reply parses and has the expected shape
    - every claim cites at least one chunk, and only chunks it was given
    - every number in a claim appears in a chunk it cites
    - each claim shares enough of its words with what it cites
    - "not found" carries no claims

A failing answer is sent back once with the problems listed. If it fails
again it is rejected and the system says it cannot answer, rather than pass
on an answer whose citations do not hold.

The model sits behind `Generate`, a function from prompt to text, so the
checks are tested with scripted replies and nothing here spends money.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

NOT_FOUND = "Not found in the corpus."
# Share of a claim's content words that must appear in the chunks it cites.
SUPPORT_FLOOR = 0.5
_STOP = frozenset(
    "a an and are as at be by can do does for from has have how if in is it its "
    "may must of on or shall should that the their there this to under what when "
    "where which who whom why will with within any all such been also not no".split()
)

Generate = Callable[[str, str], str]  # (system prompt, user prompt) -> reply text

SYSTEM = """You answer questions about Reserve Bank of India circulars for a compliance team.
Use only the numbered context chunks you are given. Do not use outside knowledge.

Reply with JSON only, in exactly this shape:
{"not_found": false, "claims": [{"text": "...", "citations": ["<chunk id>", ...]}]}

Rules:
- Each claim is one sentence that answers part of the question.
- Every claim cites the chunk IDs that support it, copied exactly from the context.
- Copy numbers, amounts, dates and time limits exactly as the chunk states them.
- If the context does not answer the question, reply {"not_found": true, "claims": []}.
"""


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: str
    title: str
    text: str


class Claim(BaseModel):
    text: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)


class Reply(BaseModel):
    not_found: bool
    claims: list[Claim] = Field(default_factory=list)


@dataclass
class Answer:
    status: Literal["answered", "not_found", "rejected"]
    claims: list[Claim] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # from the last attempt
    attempts: int = 1
    raw: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        if self.status != "answered":
            return NOT_FOUND
        return " ".join(f"{c.text} [{', '.join(c.citations)}]" for c in self.claims)

    @property
    def cited(self) -> list[str]:
        return list(dict.fromkeys(cid for c in self.claims for cid in c.citations))


def user_prompt(question: str, chunks: Sequence[ContextChunk]) -> str:
    context = "\n\n".join(f"[{c.chunk_id}] {c.title}\n{c.text}" for c in chunks)
    return f"Context:\n{context}\n\nQuestion: {question}"


_NUMBER = re.compile(r"\d+(?:[.,/:-]\d+)*")


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in _NUMBER.findall(text)}


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2}


def parse(reply: str) -> Reply:
    """The JSON object in a reply; tolerates a code fence around it."""
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return Reply.model_validate(json.loads(text[start : end + 1]))


def problems(reply: Reply, chunks: Sequence[ContextChunk]) -> list[str]:
    """Why the reply's citations do not hold; empty when they do."""
    found: list[str] = []
    by_id = {c.chunk_id: c for c in chunks}
    if reply.not_found:
        if reply.claims:
            found.append("says not found but also makes claims")
        return found
    if not reply.claims:
        found.append("makes no claims and does not say not found")
    for n, claim in enumerate(reply.claims, 1):
        if not claim.citations:
            found.append(f"claim {n} cites nothing")
            continue
        unknown = [cid for cid in claim.citations if cid not in by_id]
        if unknown:
            found.append(f"claim {n} cites chunks it was not given: {', '.join(unknown)}")
            continue
        cited_text = " ".join(by_id[cid].text for cid in claim.citations)
        missing = sorted(_numbers(claim.text) - _numbers(cited_text))
        if missing:
            found.append(f"claim {n} states numbers its citations do not: {', '.join(missing)}")
        words = _content(claim.text)
        if words:
            share = len(words & _content(cited_text)) / len(words)
            if share < SUPPORT_FLOOR:
                found.append(f"claim {n} shares only {share:.0%} of its words with what it cites")
    return found


def _feedback(found: Sequence[str]) -> str:
    listed = "\n".join(f"- {p}" for p in found)
    return (
        "Your previous reply was rejected for these reasons:\n"
        f"{listed}\n"
        "Reply again with JSON only, citing only the given chunk IDs, or say not found."
    )


def answer(
    question: str, chunks: Sequence[ContextChunk], generate: Generate, retries: int = 1
) -> Answer:
    """Ask, check, and retry once with the problems; reject if they remain."""
    prompt = user_prompt(question, chunks)
    raw: list[str] = []
    found: list[str] = []
    reply: Reply | None = None
    for attempt in range(1, retries + 2):
        text = generate(SYSTEM, prompt if attempt == 1 else f"{prompt}\n\n{_feedback(found)}")
        raw.append(text)
        try:
            reply = parse(text)
        except (ValueError, ValidationError) as error:
            found = [f"reply is not the required JSON: {str(error).splitlines()[0]}"]
            reply = None
            continue
        found = problems(reply, chunks)
        if not found:
            status: Literal["answered", "not_found"] = (
                "not_found" if reply.not_found else "answered"
            )
            return Answer(status, list(reply.claims), [], attempt, raw)
    return Answer("rejected", list(reply.claims) if reply else [], found, retries + 1, raw)
