"""Indexing chunks in Qdrant, and retrieving them: dense, sparse, hybrid, reranked.

    docker compose up -d qdrant
    uv run python -m regradar.index build --strategy section
    uv run python -m regradar.index search "within how many hours report a cyber incident" \
        --mode hybrid --rerank --date-from 2024-01-01

One collection per chunking strategy. Each point holds three vectors over the
same text (the document title, then the chunk): `granite` and `bge` (dense)
and `bm25` (sparse; Qdrant applies the IDF). Hybrid search fuses granite and
BM25 with reciprocal rank fusion inside Qdrant; the cross-encoder then
re-scores the top candidates. Filters narrow every mode by regulator, date
range, circular number, kind or document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

import numpy as np
from qdrant_client import QdrantClient, models

from regradar.chunking import STRATEGIES, Chunk, CleanDocument, load_corpus

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "corpus" / "manifest.jsonl"
VECTOR_CACHE = ROOT / "data" / "vectors"

DENSE_MODELS = {
    "granite": "ibm-granite/granite-embedding-small-english-r2",
    "bge": "BAAI/bge-small-en-v1.5",
}
SPARSE_MODEL = "Qdrant/bm25"
RERANKER = "Xenova/ms-marco-MiniLM-L-12-v2"
DENSE_DIM = 384
MODES = ("granite", "bge", "bm25", "hybrid")
CANDIDATES = 50  # retrieved per arm before fusion, and before reranking
BATCH = 8  # embedding batch: what a 16 GB Mac runs beside Qdrant


def collection(strategy: str) -> str:
    return f"regradar_{strategy}"


def point_id(chunk_id: str) -> str:
    """A UUID derived from the chunk ID, so re-indexing replaces, not duplicates."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"regradar:{chunk_id}"))


def embed_text(title: str, chunk: Chunk) -> str:
    """What every model sees: the same text, so the ablation compares models."""
    return f"{title}\n\n{chunk.text}"


def metadata() -> dict[str, dict[str, Any]]:
    rows = (json.loads(line) for line in MANIFEST.open(encoding="utf-8"))
    return {row["doc_id"]: row for row in rows if row.get("in_corpus")}


def payload(chunk: Chunk, doc: CleanDocument, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "start": chunk.start,
        "end": chunk.end,
        "page": chunk.page,
        "section": chunk.section,
        "text": chunk.text,
        "title": doc.title,
        "regulator": meta.get("regulator", "RBI"),
        "kind": meta.get("kind"),
        "circular_number": meta.get("circular_number"),
        "department": meta.get("department"),
        # RFC 3339, so Qdrant's datetime index can range-filter it.
        "date": f"{meta['date']}T00:00:00Z" if meta.get("date") else None,
        "page_url": meta.get("page_url"),
    }


# --- embedding, with a cache keyed by the text --------------------------------


def _cache_paths(model: str, strategy: str) -> tuple[Path, Path]:
    folder = VECTOR_CACHE / model
    return folder / f"{strategy}.npy", folder / f"{strategy}.keys.json"


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def dense_vectors(model: str, strategy: str, texts: Sequence[str]) -> np.ndarray:
    """Vectors for `texts`, computing only those not cached from a previous run."""
    from fastembed import TextEmbedding

    vectors_path, keys_path = _cache_paths(model, strategy)
    cached: dict[str, np.ndarray] = {}
    if vectors_path.exists() and keys_path.exists():
        stored = np.load(vectors_path)
        keys = json.loads(keys_path.read_text(encoding="utf-8"))
        cached = dict(zip(keys, stored, strict=True))
    keys = [_key(text) for text in texts]
    todo = [i for i, key in enumerate(keys) if key not in cached]
    if todo:
        embedder = TextEmbedding(DENSE_MODELS[model])
        started = time.perf_counter()
        fresh = embedder.embed([texts[i] for i in todo], batch_size=BATCH)
        for i, vector in zip(todo, fresh, strict=True):
            cached[keys[i]] = np.asarray(vector, dtype=np.float32)
        print(
            f"  {model}: embedded {len(todo)} chunks in {time.perf_counter() - started:.0f} s",
            file=sys.stderr,
        )
    matrix = np.stack([cached[key] for key in keys])
    vectors_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, matrix)
    keys_path.write_text(json.dumps(keys), encoding="utf-8")
    return matrix


def sparse_vectors(texts: Iterable[str]) -> list[models.SparseVector]:
    from fastembed import SparseTextEmbedding

    embedder = SparseTextEmbedding(SPARSE_MODEL)
    return [
        models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
        for e in embedder.embed(list(texts), batch_size=64)
    ]


# --- building a collection ----------------------------------------------------


def corpus_chunks(strategy: str) -> list[tuple[Chunk, CleanDocument]]:
    chunker = STRATEGIES[strategy]
    return [(chunk, doc) for doc in load_corpus() for chunk in chunker(doc)]


def create_collection(client: QdrantClient, name: str, dim: int = DENSE_DIM) -> None:
    """A fresh collection: two dense vectors, BM25 with IDF, and payload indexes
    for the filters."""
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name,
        vectors_config={
            model: models.VectorParams(size=dim, distance=models.Distance.COSINE)
            for model in DENSE_MODELS
        },
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for field_name, schema in (
        ("doc_id", models.PayloadSchemaType.KEYWORD),
        ("regulator", models.PayloadSchemaType.KEYWORD),
        ("kind", models.PayloadSchemaType.KEYWORD),
        ("circular_number", models.PayloadSchemaType.KEYWORD),
        ("department", models.PayloadSchemaType.KEYWORD),
        ("date", models.PayloadSchemaType.DATETIME),
    ):
        client.create_payload_index(name, field_name, field_schema=schema)


def build(client: QdrantClient, strategy: str) -> int:
    """(Re)create the strategy's collection and fill it. Returns the point count."""
    meta = metadata()
    pairs = corpus_chunks(strategy)
    texts = [embed_text(doc.title, chunk) for chunk, doc in pairs]
    dense = {model: dense_vectors(model, strategy, texts) for model in DENSE_MODELS}
    sparse = sparse_vectors(texts)

    name = collection(strategy)
    create_collection(client, name)

    points = [
        models.PointStruct(
            id=point_id(chunk.chunk_id),
            vector={
                **{model: dense[model][i].tolist() for model in DENSE_MODELS},
                "bm25": sparse[i],
            },
            payload=payload(chunk, doc, meta[doc.doc_id]),
        )
        for i, (chunk, doc) in enumerate(pairs)
    ]
    for start in range(0, len(points), 256):
        client.upsert(name, points[start : start + 256], wait=True)
    return len(points)


# --- searching ----------------------------------------------------------------


@dataclass
class Filters:
    regulator: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    circular_number: str | None = None
    kinds: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)

    def to_qdrant(self) -> models.Filter | None:
        must: list[models.Condition] = []
        if self.regulator:
            must.append(
                models.FieldCondition(
                    key="regulator", match=models.MatchValue(value=self.regulator)
                )
            )
        if self.circular_number:
            must.append(
                models.FieldCondition(
                    key="circular_number", match=models.MatchValue(value=self.circular_number)
                )
            )
        if self.kinds:
            must.append(models.FieldCondition(key="kind", match=models.MatchAny(any=self.kinds)))
        if self.doc_ids:
            must.append(
                models.FieldCondition(key="doc_id", match=models.MatchAny(any=self.doc_ids))
            )
        if self.date_from or self.date_to:
            must.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=datetime.combine(self.date_from, dtime.min, UTC)
                        if self.date_from
                        else None,
                        lte=datetime.combine(self.date_to, dtime.max, UTC)
                        if self.date_to
                        else None,
                    ),
                )
            )
        return models.Filter(must=must) if must else None


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    start: int
    end: int
    score: float
    payload: dict[str, Any]


RRF_K = 2  # Qdrant's default


def rrf(rankings: Sequence[Sequence[Hit]], k: int = RRF_K) -> list[Hit]:
    """Reciprocal rank fusion: sum of 1 / (k + rank), ranks from 0, as Qdrant
    computes it; ties go to the smaller chunk ID, so the order never varies."""
    scores: dict[str, float] = {}
    first: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            first.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [
        Hit(
            first[c].chunk_id,
            first[c].doc_id,
            first[c].start,
            first[c].end,
            scores[c],
            first[c].payload,
        )
        for c in order
    ]


class QueryEncoders:
    """The fastembed models that turn a query into vectors. Loaded once."""

    def __init__(self) -> None:
        from fastembed import SparseTextEmbedding, TextEmbedding

        self._dense = {model: TextEmbedding(path) for model, path in DENSE_MODELS.items()}
        self._sparse = SparseTextEmbedding(SPARSE_MODEL)

    def dense(self, model: str, query: str) -> list[float]:
        return [float(x) for x in next(iter(self._dense[model].query_embed(query)))]

    def sparse(self, query: str) -> models.SparseVector:
        e = next(iter(self._sparse.query_embed(query)))
        return models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())


class CrossEncoder:
    """Scores (query, passage) pairs; loaded on first use."""

    def __init__(self, name: str = RERANKER) -> None:
        self.name = name
        self._model: Any = None

    def __call__(self, query: str, passages: Sequence[str]) -> list[float]:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(self.name)
        return [float(score) for score in self._model.rerank(query, list(passages))]


class Retriever:
    """One call to Qdrant per search, plus the cross-encoder when reranking.
    Encoders and reranker can be replaced (the tests use small fakes)."""

    def __init__(
        self,
        client: QdrantClient,
        strategy: str,
        encoders: Any = None,
        reranker: Any = None,
        name: str | None = None,
    ) -> None:
        self.client = client
        self.name = name or collection(strategy)
        self.encoders = encoders if encoders is not None else QueryEncoders()
        self.reranker = reranker if reranker is not None else CrossEncoder()

    def _query_dense(self, model: str, query: str) -> list[float]:
        vector: list[float] = self.encoders.dense(model, query)
        return vector

    def _query_sparse(self, query: str) -> models.SparseVector:
        vector: models.SparseVector = self.encoders.sparse(query)
        return vector

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        k: int = 10,
        rerank: bool = False,
        filters: Filters | None = None,
        candidates: int = CANDIDATES,
    ) -> list[Hit]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        flt = filters.to_qdrant() if filters else None
        limit = candidates if rerank else k
        if mode == "hybrid":
            # Fused here rather than in Qdrant: each arm on its own returns the
            # same results every time, but Qdrant's server-side RRF broke ties
            # differently between calls (9 of 40 queries changed their top 5 on
            # an immediate repeat). Same formula as Qdrant's (k = 2, ranks from
            # 0), with ties broken by chunk ID.
            dense = self._arm(self._query_dense("granite", query), "granite", flt, candidates)
            sparse = self._arm(self._query_sparse(query), "bm25", flt, candidates)
            hits = rrf([dense, sparse])[:limit]
        else:
            vector: Any = (
                self._query_sparse(query) if mode == "bm25" else self._query_dense(mode, query)
            )
            hits = self._arm(vector, mode, flt, limit)
        return self._rerank(query, hits)[:k] if rerank else hits[:k]

    def _arm(self, vector: Any, using: str, flt: models.Filter | None, limit: int) -> list[Hit]:
        response = self.client.query_points(
            self.name, query=vector, using=using, query_filter=flt, limit=limit, with_payload=True
        )
        return [
            Hit(
                chunk_id=p.payload["chunk_id"],
                doc_id=p.payload["doc_id"],
                start=p.payload["start"],
                end=p.payload["end"],
                score=float(p.score),
                payload=p.payload,
            )
            for p in response.points
            if p.payload
        ]

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return hits
        texts = [f"{h.payload['title']}\n\n{h.payload['text']}" for h in hits]
        scores = self.reranker(query, texts)
        order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)
        return [
            Hit(
                hits[i].chunk_id,
                hits[i].doc_id,
                hits[i].start,
                hits[i].end,
                float(scores[i]),
                hits[i].payload,
            )
            for i in order
        ]


def connect(url: str = "http://127.0.0.1:6333") -> QdrantClient:
    return QdrantClient(url=url, timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    b = steps.add_parser("build", help="embed and index one chunking strategy (or all)")
    b.add_argument("--strategy", choices=[*STRATEGIES, "all"], default="all")
    s = steps.add_parser("search", help="search one collection")
    s.add_argument("query")
    s.add_argument("--strategy", choices=list(STRATEGIES), default="section")
    s.add_argument("--mode", choices=MODES, default="hybrid")
    s.add_argument("--rerank", action="store_true")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--date-from", type=date.fromisoformat)
    s.add_argument("--date-to", type=date.fromisoformat)
    s.add_argument("--circular-number")
    s.add_argument("--kind", action="append", default=[])
    args = parser.parse_args(argv)
    client = connect()
    if args.step == "build":
        for strategy in STRATEGIES if args.strategy == "all" else [args.strategy]:
            started = time.perf_counter()
            count = build(client, strategy)
            print(
                f"{collection(strategy)}: {count} points in {time.perf_counter() - started:.0f} s"
            )
        return 0
    retriever = Retriever(client, args.strategy)
    filters = Filters(
        date_from=args.date_from,
        date_to=args.date_to,
        circular_number=args.circular_number,
        kinds=args.kind,
    )
    started = time.perf_counter()
    hits = retriever.search(args.query, args.mode, args.k, args.rerank, filters)
    elapsed = (time.perf_counter() - started) * 1000
    for rank, hit in enumerate(hits, 1):
        p = hit.payload
        print(
            f"{rank}. {hit.score:.4f}  {hit.chunk_id}  [{p.get('section') or '-'}] p{p.get('page')}"
        )
        print(f"   {p['title'][:90]} ({(p.get('date') or '')[:10]})")
        print(f"   {' '.join(p['text'].split())[:220]}")
    print(f"({elapsed:.0f} ms)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
