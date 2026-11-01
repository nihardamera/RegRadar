"""Speed, memory and truncation of candidate embedding models on this Mac.

Not a quality comparison: quality is measured on the golden set (M3), and
nothing is chosen on quality before that exists. This answers the questions
that can be answered now: how long does the corpus take to embed, how fast is
one query, how much memory, and how much of a passage does each model cut off.

    uv run python scripts/bench_embeddings.py            # all candidates
    uv run python scripts/bench_embeddings.py --passages 64   # quick run

Each model runs in its own process, so peak memory is that model's alone.
Results: eval/embedding_speed.json.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from regradar.chunking import CHUNK_WORDS  # noqa: E402

CANDIDATES = [
    "BAAI/bge-small-en-v1.5",
    "ibm-granite/granite-embedding-small-english-r2",
    "nomic-ai/nomic-embed-text-v1.5",
    "snowflake/snowflake-arctic-embed-m-long",
]
# The chunker's target size, so truncation figures describe real chunks.
PASSAGE_WORDS = CHUNK_WORDS
# Batch 32 took a long-context model to 7 GB and the next one out of memory on
# a 16 GB Mac; 8 is what this machine can run alongside Qdrant.
BATCH_SIZE = 8
QUERIES = [
    "Within how many hours must a payment system operator report a cyber incident to RBI?",
    "Can penal charges on a loan be capitalised?",
    "What is the cap on default loss guarantee in digital lending?",
    "How often must credit institutions report credit information to CICs?",
    "What net worth must a payment aggregator have by the end of the third year?",
]


def passages(count: int, seed: int = 7) -> list[str]:
    """`count` passages of PASSAGE_WORDS words, sampled from the committed corpus."""
    windows: list[str] = []
    for path in sorted((ROOT / "corpus" / "docs").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        tokens = " ".join(page["text"] for page in document["pages"]).split()
        windows += [
            " ".join(tokens[i : i + PASSAGE_WORDS])
            for i in range(0, max(1, len(tokens) - PASSAGE_WORDS), PASSAGE_WORDS)
        ]
    return random.Random(seed).sample(windows, min(count, len(windows)))


def corpus_windows() -> int:
    total = 0
    for path in (ROOT / "corpus" / "docs").glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        words = sum(len(page["text"].split()) for page in document["pages"])
        total += max(1, words // PASSAGE_WORDS)
    return total


def peak_rss_mb() -> float:
    # ru_maxrss is in bytes on macOS and kilobytes on Linux.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3


def measure(model_name: str, count: int) -> dict[str, Any]:
    from fastembed import TextEmbedding

    texts = passages(count)
    started = time.perf_counter()
    model = TextEmbedding(model_name)
    load_s = time.perf_counter() - started

    tokenizer = model.model.tokenizer  # type: ignore[attr-defined]
    limit = tokenizer.truncation["max_length"] if tokenizer.truncation else None
    tokenizer.no_truncation()
    lengths = [len(tokenizer.encode(text).ids) for text in texts]
    if limit:
        tokenizer.enable_truncation(limit)
    over = [n for n in lengths if limit and n > limit]
    cut = sum(n - limit for n in over) / sum(lengths) if limit else 0.0

    list(model.embed(texts[:8]))  # warm-up
    started = time.perf_counter()
    vectors = list(model.embed(texts, batch_size=BATCH_SIZE))
    embed_s = time.perf_counter() - started

    latencies = []
    for _ in range(4):
        for query in QUERIES:
            started = time.perf_counter()
            list(model.query_embed(query))
            latencies.append((time.perf_counter() - started) * 1000)

    per_second = len(texts) / embed_s
    return {
        "model": model_name,
        "dim": len(vectors[0]),
        "max_tokens": limit,
        "load_s": round(load_s, 1),
        "passages": len(texts),
        "passages_per_s": round(per_second, 1),
        "corpus_minutes": round(corpus_windows() / per_second / 60, 1),
        "query_ms_median": round(statistics.median(latencies), 1),
        "query_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1),
        "peak_rss_mb": round(peak_rss_mb()),
        "tokens_median": statistics.median(lengths),
        "share_over_limit": round(len(over) / len(lengths), 3),
        "share_of_tokens_cut": round(cut, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passages", type=int, default=512)
    parser.add_argument("--model", help="measure one model, in this process (used internally)")
    args = parser.parse_args()
    if args.model:
        print(json.dumps(measure(args.model, args.passages)))
        return 0

    results = []
    for name in CANDIDATES:
        print(f"measuring {name} ...", file=sys.stderr, flush=True)
        run = subprocess.run(
            [sys.executable, __file__, "--model", name, "--passages", str(args.passages)],
            capture_output=True,
            text=True,
        )
        if run.returncode == 0:
            results.append(json.loads(run.stdout.strip().splitlines()[-1]))
        else:
            # A model killed for memory is a result too: it cannot run here.
            reason = f"exit {run.returncode}" + (
                " (killed: out of memory?)" if run.returncode == -9 else ""
            )
            results.append({"model": name, "failed": reason, "stderr": run.stderr[-500:]})
        print(json.dumps(results[-1])[:300], file=sys.stderr)
    out = {
        "machine": f"{platform.machine()} {platform.mac_ver()[0] or platform.platform()}",
        "processor": subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
        ).stdout.strip(),
        "passage_words": PASSAGE_WORDS,
        "batch_size": BATCH_SIZE,
        "corpus_passages": corpus_windows(),
        "results": results,
    }
    path = ROOT / "eval" / "embedding_speed.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"-> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
