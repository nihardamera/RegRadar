"""Hard cases for judge calibration: real failures, and answers with one planted error.

Citation enforcement leaves few unfaithful answers, and Cohen's kappa means
little when nearly every human label is "yes": a judge that always says yes
agrees 95% of the time and scores kappa 0. So the human labels also cover:

    rejected       answers the code checks rejected (the last attempt's claims)
    unanswerable   answers given to questions the corpus cannot answer
    planted        a real answer with one claim changed by a fixed rule

The planted changes are the errors a faithfulness judge exists to catch:

    number        a number changed to one the cited text does not contain
    negation      "shall not" -> "shall", "may" -> "shall", and so on
    entity        banks <-> non-banks, debit <-> credit, import <-> export
    condition     an "unless ...", "provided ...", "only if ..." clause dropped
    wrong_chunk   a claim's citation moved to a retrieved chunk it did not cite

A rule does not guarantee an error (a dropped clause can be harmless), so the
change is recorded and the human label decides. The labeller is not told
which cases are planted. Everything here is fixed by a seed and runs before
any judge does.
"""

from __future__ import annotations

import copy
import random
import re
from collections.abc import Callable, Sequence
from typing import Any

Record = dict[str, Any]
KINDS = ("number", "negation", "entity", "condition", "wrong_chunk")
PER_KIND = 6

_NUMBER = re.compile(r"(?<![\w/.-])\d+(?:,\d{2,3})*(?:\.\d+)?(?![\w/-])")
_NEGATIONS: list[tuple[str, str]] = [
    (r"\bshall not\b", "shall"),
    (r"\bmust not\b", "must"),
    (r"\bis not permitted\b", "is permitted"),
    (r"\bare not permitted\b", "are permitted"),
    (r"\bnot required\b", "required"),
    (r"\bcannot\b", "can"),
    (r"\bmay not\b", "may"),
    (r"\bmay\b(?!\s+\d)", "shall"),  # not the month
    (r"\bshall\b", "may"),
    (r"\bmust\b", "may"),
]
_ENTITIES: list[tuple[str, str]] = [
    (r"\bnon-bank(?!ing)", "bank"),
    (r"(?<![-\w])bank(?=s?\b)(?!\s+(?:of|accounts?)\b)", "non-bank"),  # not "Bank of India"
    (r"\bdebit card", "credit card"),
    (r"\bcredit card", "debit card"),
    (r"\bimport", "export"),
    (r"\bexport", "import"),
    (r"\bdomestic\b", "cross-border"),
    (r"\bcross-border\b", "domestic"),
]
# "provided" and "subject to" are also ordinary verbs ("provided by the issuer",
# "is subject to a cap"), so they count as conditions only after a comma.
_CONDITION = re.compile(
    r"(?:,?\s+(?:unless|only if|only when)|,\s+(?:provided|subject to|except|as long as))"
    r"\b[^.;]*",
    re.IGNORECASE,
)
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
)
_DAY = re.compile(rf"{_MONTH}\s+$|^,?\s+{_MONTH}", re.IGNORECASE)
_REPEAT = re.compile(r"\b([\w-]+?)s? (?:or|and|/) \1s?\b", re.IGNORECASE)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _cited(record: Record, claim: dict[str, Any]) -> str:
    return " ".join(record["context"].get(cid, "") for cid in claim["citations"])


def _match_case(original: str, new: str) -> str:
    return new[:1].upper() + new[1:] if original[:1].isupper() else new


def _other_number(token: str, cited: str) -> str | None:
    """A nearby value that the cited text does not contain.

    Only the leading digit group changes, so the grouping stays as written
    (₹1,00,000 -> ₹2,00,000, not ₹200,000).
    """
    if "." in token:
        return None
    head, sep, rest = token.partition(",")
    value = int(head)
    if not sep and 1900 <= value <= 2100:  # a year
        candidates = [value - 1, value + 1, value - 2]
    else:
        candidates = [value * 2, value + max(1, value // 2), value + 1]
    for new in candidates:
        text = f"{new}{sep}{rest}"
        if _digits(text) not in _digits(cited):
            return text
    return None


def _number(text: str, cited: str, rng: random.Random) -> str | None:
    tokens = [
        m
        for m in _NUMBER.finditer(text)
        if _digits(m.group()) in _digits(cited)
        # A day of the month: changing it gives "March 62", which nobody misses.
        and not _DAY.search(text[max(0, m.start() - 12) : m.start()])
        and not _DAY.search(text[m.end() : m.end() + 12])
    ]
    rng.shuffle(tokens)
    for m in tokens:
        new = _other_number(m.group(), cited)
        if new:
            return text[: m.start()] + new + text[m.end() :]
    return None


def _first_rule(
    rules: Sequence[tuple[str, str]],
) -> Callable[[str, str, random.Random], str | None]:
    def change(text: str, _cited: str, _rng: random.Random) -> str | None:
        for pattern, new in rules:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                changed = text[: m.start()] + _match_case(m.group(), new) + text[m.end() :]
                # "a bank or bank PPI issuer" gives itself away.
                return None if _REPEAT.search(changed) else changed
        return None

    return change


def _condition(text: str, _cited: str, _rng: random.Random) -> str | None:
    m = _CONDITION.search(text)
    if not m:
        return None
    changed = (text[: m.start()] + text[m.end() :]).strip()
    return changed if len(changed.split()) >= 5 else None


TEXT_CHANGES: dict[str, Callable[[str, str, random.Random], str | None]] = {
    "number": _number,
    "negation": _first_rule(_NEGATIONS),
    "entity": _first_rule(_ENTITIES),
    "condition": _condition,
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def plant(record: Record, kind: str, rng: random.Random) -> Record | None:
    """A copy of the record with one claim changed, or None if the rule finds nothing."""
    order = list(range(len(record["claims"])))
    rng.shuffle(order)
    for i in order:
        claim = record["claims"][i]
        if not claim["citations"]:
            continue
        out = copy.deepcopy(record)
        new_claim = out["claims"][i]
        if kind == "wrong_chunk":
            cited = {cid for c in record["claims"] for cid in c["citations"]}
            spare = sorted(cid for cid in record["context"] if cid not in cited)
            if not spare:
                continue
            words = _words(claim["text"])
            # The retrieved chunk that shares least with the claim: a clear miscitation.
            target = min(spare, key=lambda cid: (len(words & _words(record["context"][cid])), cid))
            new_claim["citations"] = [target]
            before, after = ", ".join(claim["citations"]), target
        else:
            changed = TEXT_CHANGES[kind](claim["text"], _cited(record, claim), rng)
            if changed is None or changed == claim["text"]:
                continue
            new_claim["text"] = changed
            before, after = claim["text"], changed
        out["planted"] = {"kind": kind, "claim": i + 1, "before": before, "after": after}
        return out
    return None


def planted_cases(
    answered: Sequence[Record], sampled: set[str], seed: int, per_kind: int = PER_KIND
) -> list[Record]:
    """`per_kind` planted cases of each kind, each from a different answer.

    Answers outside the natural sample (`sampled`, by question ID) go first, so
    fewer questions appear twice in the labelling queue.
    """
    rng = random.Random(seed)
    pool = sorted(answered, key=lambda r: r["question_id"])
    rng.shuffle(pool)
    pool.sort(key=lambda r: r["question_id"] in sampled)  # stable: outside the sample first
    used: set[str] = set()
    out: list[Record] = []
    for kind in KINDS:
        made = 0
        for record in pool:
            if made == per_kind:
                break
            if record["question_id"] in used:
                continue
            case = plant(record, kind, rng)
            if case is not None:
                used.add(record["question_id"])
                out.append(
                    {**case, "source": "planted", "case_id": f"{case['question_id']}~{kind}"}
                )
                made += 1
    return out
