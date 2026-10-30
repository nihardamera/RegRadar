"""Retrieval metrics on the golden set, with bootstrap confidence intervals.

A retrieved chunk is relevant when it overlaps a gold span (same document,
overlapping character ranges), so every chunking strategy is scored against
the same answers. Per answerable question, over the top k:

    hit@k          every part of the answer is touched by some chunk
    span_recall@k  per part, the share of its best span's characters the top k
                   cover together (an answer split across two chunks still
                   counts), averaged over parts
    mrr            1 / rank of the first chunk overlapping any gold span
    ndcg@10        a chunk gains for each part it covers that no higher chunk
                   did; the ideal ranks every part first. Part-based, so a
                   strategy that cuts an answer into more pieces gains nothing
    words@k        words in the top k: what the generator would have to read

Unanswerable questions have no retrieval target; their top score is kept for
choosing an abstention threshold later.

    uv run python -m regradar.evaluate --split dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from regradar.golden import Part, Question, Span, load

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
CACHE = ROOT / "data" / "eval_cache"
KS = (1, 5, 10)
BOOTSTRAP = 10_000
SEED = 20261031


@dataclass(frozen=True)
class Retrieved:
    """One retrieved chunk, as the metrics need it."""

    chunk_id: str
    doc_id: str
    start: int
    end: int
    words: int


def overlaps(chunk: Retrieved, span: Span) -> bool:
    return chunk.doc_id == span.doc_id and chunk.start < span.end and span.start < chunk.end


def _covered(chunks: Sequence[Retrieved], span: Span) -> float:
    """Share of `span`'s characters inside the union of `chunks`."""
    length = span.end - span.start
    if length <= 0:
        return 0.0
    hits = sorted(
        (max(c.start, span.start), min(c.end, span.end)) for c in chunks if overlaps(c, span)
    )
    covered, reach = 0, span.start
    for start, end in hits:
        start = max(start, reach)
        if end > start:
            covered += end - start
            reach = end
    return covered / length


def part_found(chunks: Sequence[Retrieved], part: Part) -> bool:
    return any(overlaps(c, s) for c in chunks for s in part.spans)


def part_recall(chunks: Sequence[Retrieved], part: Part) -> float:
    return max(_covered(chunks, span) for span in part.spans)


def ndcg(ranked: Sequence[Retrieved], parts: Sequence[Part], k: int = 10) -> float:
    found: set[int] = set()
    dcg = 0.0
    for rank, chunk in enumerate(ranked[:k], 1):
        new = [i for i, p in enumerate(parts) if i not in found and part_found([chunk], p)]
        found.update(new)
        dcg += len(new) / math.log2(rank + 1)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(parts), k) + 1))
    return dcg / ideal if ideal else 0.0


def question_metrics(ranked: Sequence[Retrieved], question: Question) -> dict[str, float]:
    parts = question.gold
    out: dict[str, float] = {}
    for k in KS:
        top = ranked[:k]
        out[f"hit@{k}"] = float(all(part_found(top, p) for p in parts))
        out[f"span_recall@{k}"] = sum(part_recall(top, p) for p in parts) / len(parts)
        out[f"words@{k}"] = float(sum(c.words for c in top))
    first = next(
        (rank for rank, c in enumerate(ranked, 1) if any(part_found([c], p) for p in parts)), None
    )
    out["mrr"] = 1 / first if first else 0.0
    out["ndcg@10"] = ndcg(ranked, parts, 10)
    return out


# --- confidence intervals -----------------------------------------------------


def bootstrap_ci(
    values: Sequence[float], resamples: int = BOOTSTRAP, seed: int = SEED
) -> tuple[float, float, float]:
    """Mean and 95% percentile-bootstrap interval, resampling questions."""
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return (math.nan, math.nan, math.nan)
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, data.size, size=(resamples, data.size))].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return (float(data.mean()), float(low), float(high))


def paired_difference_ci(
    a: Sequence[float], b: Sequence[float], resamples: int = BOOTSTRAP, seed: int = SEED
) -> tuple[float, float, float]:
    """Mean of (b - a) and its 95% interval, resampling the same questions for
    both: the paired comparison is what says whether b beats a."""
    if len(a) != len(b):
        raise ValueError("paired samples must be the same questions")
    return bootstrap_ci([y - x for x, y in zip(a, b, strict=True)], resamples, seed)


# --- running a configuration ----------------------------------------------------


@dataclass(frozen=True)
class Config:
    strategy: str
    mode: str
    rerank: int = 0  # candidates reranked; 0 = no reranking

    @property
    def name(self) -> str:
        return f"{self.strategy}/{self.mode}" + (f"+rerank{self.rerank}" if self.rerank else "")


@dataclass
class ConfigResult:
    config: str
    questions: int
    metrics: dict[str, tuple[float, float, float]]
    per_question: dict[str, dict[str, float]] = field(default_factory=dict)
    unanswerable_top_scores: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0


Search = Callable[[Question, Config], list[tuple[Retrieved, float]]]


def _cache_key(question: Question, config: Config) -> str:
    raw = f"{config.name}|{question.id}|{question.question}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def run(
    questions: Sequence[Question],
    config: Config,
    search: Search,
    cache_dir: Path | None = CACHE,
) -> ConfigResult:
    """Score one configuration. Retrieval is cached by question text and
    configuration, so a rerun (or the CI gate) need not query again."""
    cache: dict[str, Any] = {}
    cache_file = cache_dir / f"{config.name.replace('/', '_')}.json" if cache_dir else None
    if cache_file and cache_file.exists():
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    started = time.perf_counter()
    per_question: dict[str, dict[str, float]] = {}
    top_scores: dict[str, float] = {}
    for question in questions:
        key = _cache_key(question, config)
        if key not in cache:
            hits = search(question, config)
            cache[key] = [[asdict(chunk), score] for chunk, score in hits]
        ranked = [(Retrieved(**chunk), score) for chunk, score in cache[key]]
        if question.answerable:
            per_question[question.id] = question_metrics([c for c, _ in ranked], question)
        else:
            top_scores[question.id] = ranked[0][1] if ranked else 0.0
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
    names = next(iter(per_question.values())).keys() if per_question else []
    metrics = {name: bootstrap_ci([per_question[q][name] for q in per_question]) for name in names}
    return ConfigResult(
        config=config.name,
        questions=len(per_question),
        metrics=metrics,
        per_question=per_question,
        unanswerable_top_scores=top_scores,
        seconds=round(time.perf_counter() - started, 1),
    )


def ablation_configs() -> list[Config]:
    """Chunking x retriever x reranking, as planned for M3."""
    configs = [
        Config(strategy, mode)
        for strategy in ("fixed", "recursive", "section")
        for mode in ("granite", "bge", "bm25", "hybrid")
    ]
    configs += [
        Config(strategy, "hybrid", depth)
        for strategy in ("fixed", "recursive", "section")
        for depth in (20, 50)
    ]
    return configs


def qdrant_search() -> Search:
    """The real retriever, one per strategy, created on first use."""
    from regradar.index import Retriever, connect

    client = connect()
    retrievers: dict[str, Retriever] = {}

    def search(question: Question, config: Config) -> list[tuple[Retrieved, float]]:
        if config.strategy not in retrievers:
            retrievers[config.strategy] = Retriever(client, config.strategy)
        hits = retrievers[config.strategy].search(
            question.question,
            config.mode,
            k=max(KS),
            rerank=bool(config.rerank),
            candidates=config.rerank or 50,
        )
        return [
            (
                Retrieved(h.chunk_id, h.doc_id, h.start, h.end, len(h.payload["text"].split())),
                h.score,
            )
            for h in hits
        ]

    return search


def table(results: Sequence[ConfigResult], columns: Sequence[str]) -> str:
    def cell(value: tuple[float, float, float], words: bool) -> str:
        mean, low, high = value
        if words:
            return f"{mean:.0f}"
        return f"{100 * mean:.1f} [{100 * low:.1f}, {100 * high:.1f}]"

    lines = [
        "| Configuration | n | " + " | ".join(columns) + " |",
        "| --- | --- |" + " --- |" * len(columns),
    ]
    for r in results:
        cells = [cell(r.metrics[c], c.startswith("words")) for c in columns]
        lines.append(f"| {r.config} | {r.questions} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument(
        "--golden", type=Path, help="another questions file (default: the golden set)"
    )
    parser.add_argument("--only", help="run configurations whose name contains this")
    args = parser.parse_args(argv)
    questions = load(args.golden) if args.golden else load()
    if args.split != "all":
        questions = [q for q in questions if q.split == args.split]
    if not any(q.answerable for q in questions):
        print("no answerable questions in this split yet", file=sys.stderr)
        return 1
    search = qdrant_search()
    results = []
    for config in ablation_configs():
        if args.only and args.only not in config.name:
            continue
        results.append(run(questions, config, search))
        print(f"{config.name}: {results[-1].seconds} s", file=sys.stderr)
    columns = ["hit@10", "span_recall@10", "mrr", "ndcg@10", "words@10"]
    out = {
        "split": args.split,
        "golden": str(args.golden or "eval/golden/questions.jsonl"),
        "bootstrap_resamples": BOOTSTRAP,
        "results": [asdict(r) for r in results],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"retrieval_{args.split}" if not args.golden else f"retrieval_{args.golden.stem}"
    (RESULTS / f"{stem}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    markdown = table(results, columns)
    (RESULTS / f"{stem}.md").write_text(markdown + "\n", encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
