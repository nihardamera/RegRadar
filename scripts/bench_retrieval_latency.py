"""What each retrieval mode, and each reranker, costs per query on this Mac.

Latency only: what reranking buys in recall is measured on the golden set
(M3). Needs Qdrant running and the collections built:

    docker compose up -d qdrant
    uv run python -m regradar.index build
    uv run python scripts/bench_retrieval_latency.py

Results: eval/retrieval_latency.json.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from regradar.index import MODES, CrossEncoder, Retriever, connect  # noqa: E402

RERANKERS = [
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "Xenova/ms-marco-MiniLM-L-12-v2",
    "BAAI/bge-reranker-base",
]
# Shaped like the golden set's questions, but not from it.
QUERIES = [
    "Within how many hours must a payment system operator report a cyber incident to RBI?",
    "Can penal charges on a loan be capitalised?",
    "What is the cap on default loss guarantee in digital lending?",
    "How often must credit institutions report credit information to CICs?",
    "Minimum net worth for a payment aggregator by the end of the third financial year",
    "RBI/2025-26/79",
    "cooling-off period digital loan exit without penalty",
    "V-CIP recordings stored in India",
]
REPEATS = 3


def timed(fn: object, *args: object, **kwargs: object) -> float:
    started = time.perf_counter()
    fn(*args, **kwargs)  # type: ignore[operator]
    return (time.perf_counter() - started) * 1000


def summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50_ms": round(statistics.median(ordered), 1),
        "p95_ms": round(ordered[int(0.95 * (len(ordered) - 1))], 1),
    }


def main() -> int:
    client = connect()
    retriever = Retriever(client, "section")
    for query in QUERIES[:2]:  # warm-up: load models, fill caches
        retriever.search(query, "hybrid", k=10)
    results: dict[str, object] = {}
    for mode in MODES:
        runs = [timed(retriever.search, q, mode, 10) for q in QUERIES for _ in range(REPEATS)]
        results[mode] = summary(runs)
    for name in RERANKERS:
        retriever.reranker = CrossEncoder(name)
        retriever.search(QUERIES[0], "hybrid", 10, rerank=True)  # load the model
        runs = [
            timed(retriever.search, q, "hybrid", 10, rerank=True)
            for q in QUERIES
            for _ in range(REPEATS)
        ]
        results[f"hybrid + rerank top 50 ({name})"] = summary(runs)
        print(name, results[f"hybrid + rerank top 50 ({name})"], file=sys.stderr)
    out = {
        "machine": f"{platform.machine()} macOS {platform.mac_ver()[0]}",
        "processor": subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
        ).stdout.strip(),
        "collection": "regradar_section",
        "queries": len(QUERIES),
        "repeats": REPEATS,
        "k": 10,
        "rerank_candidates": 50,
        "latency": results,
    }
    path = ROOT / "eval" / "retrieval_latency.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
