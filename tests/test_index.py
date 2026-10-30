"""Retrieval against Qdrant's in-memory mode, with three-dimensional fake
vectors: the real query path (prefetch, RRF fusion, sparse IDF, payload
filters), no models and no server."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from qdrant_client import QdrantClient, models

from regradar.index import Filters, Retriever, create_collection, point_id

# Each chunk: its text, a dense vector (fake meaning) and its BM25 terms.
CHUNKS: list[dict[str, Any]] = [
    {
        "chunk_id": "rbi-n12715:section:0007",
        "doc_id": "rbi-n12715",
        "text": "Unusual incidents shall be reported to RBI within 6 hours of detection.",
        "dense": [1.0, 0.0, 0.0],
        "terms": {1: 1.0, 2: 1.0},  # incident, report
        "date": "2024-07-30",
        "kind": "master_direction",
    },
    {
        "chunk_id": "rbi-n12527:section:0003",
        "doc_id": "rbi-n12527",
        "text": "Penal charges shall not be capitalised; no further interest is computed.",
        "dense": [0.0, 1.0, 0.0],
        "terms": {3: 1.0, 4: 1.0},  # penal, charges
        "date": "2023-08-18",
        "kind": "circular",
    },
    {
        "chunk_id": "rbi-n12898:section:0001",
        "doc_id": "rbi-n12898",
        "text": "RBI/2025-26/79 Authentication mechanisms for digital payment transactions.",
        # Dense meaning close to the incident chunk; only its terms name the number.
        "dense": [0.9, 0.0, 0.44],
        "terms": {5: 1.0, 6: 1.0},  # rbi/2025-26/79, authentication
        "date": "2025-09-25",
        "kind": "directions",
    },
]

QUERIES: dict[str, dict[str, Any]] = {
    "cyber incident reporting": {"dense": [1.0, 0.0, 0.1], "terms": {1: 1.0, 2: 1.0}},
    "penal charges": {"dense": [0.0, 1.0, 0.0], "terms": {3: 1.0, 4: 1.0}},
    # A circular number: the dense model has no idea what it means.
    "RBI/2025-26/79": {"dense": [1.0, 0.0, 0.0], "terms": {5: 1.0}},
}


class FakeEncoders:
    def dense(self, model: str, query: str) -> list[float]:
        return list(QUERIES[query]["dense"])

    def sparse(self, query: str) -> models.SparseVector:
        terms = QUERIES[query]["terms"]
        return models.SparseVector(indices=list(terms), values=list(terms.values()))


def reverse_alphabetical(query: str, passages: list[str]) -> list[float]:
    """A stand-in cross-encoder whose order is easy to predict."""
    ranked = sorted(passages, reverse=True)
    return [float(len(passages) - ranked.index(p)) for p in passages]


@pytest.fixture
def retriever() -> Retriever:
    client = QdrantClient(":memory:")
    create_collection(client, "test", dim=3)
    client.upsert(
        "test",
        [
            models.PointStruct(
                id=point_id(c["chunk_id"]),
                vector={
                    "granite": c["dense"],
                    "bge": c["dense"],
                    "bm25": models.SparseVector(
                        indices=list(c["terms"]), values=list(c["terms"].values())
                    ),
                },
                payload={
                    "chunk_id": c["chunk_id"],
                    "doc_id": c["doc_id"],
                    "start": 0,
                    "end": len(c["text"]),
                    "text": c["text"],
                    "title": c["doc_id"],
                    "regulator": "RBI",
                    "kind": c["kind"],
                    "date": f"{c['date']}T00:00:00Z",
                },
            )
            for c in CHUNKS
        ],
    )
    return Retriever(client, "section", FakeEncoders(), reverse_alphabetical, name="test")


@pytest.mark.parametrize("mode", ["granite", "bge", "bm25", "hybrid"])
def test_each_mode_finds_the_chunk_that_answers(retriever: Retriever, mode: str) -> None:
    assert retriever.search("penal charges", mode, k=1)[0].doc_id == "rbi-n12527"


def test_bm25_finds_an_exact_circular_number_that_dense_misses(retriever: Retriever) -> None:
    """The M2 gate's case for hybrid: identifiers carry no meaning a dense
    model can embed, but they are exact terms for BM25."""
    assert retriever.search("RBI/2025-26/79", "granite", k=1)[0].doc_id == "rbi-n12715"
    assert retriever.search("RBI/2025-26/79", "bm25", k=1)[0].doc_id == "rbi-n12898"
    hybrid = [h.doc_id for h in retriever.search("RBI/2025-26/79", "hybrid", k=2)]
    assert "rbi-n12898" in hybrid


def test_the_reranker_reorders_the_candidates(retriever: Retriever) -> None:
    """The cross-encoder sees the title and the text, as the embedders do; the
    fake one ranks those passages in reverse alphabetical order."""
    hits = retriever.search("cyber incident reporting", "granite", k=3, rerank=True)
    assert [h.doc_id for h in hits] == ["rbi-n12898", "rbi-n12715", "rbi-n12527"]
    assert hits[0].score > hits[1].score > hits[2].score


def test_filters_narrow_every_mode(retriever: Retriever) -> None:
    recent = Filters(date_from=date(2025, 1, 1))
    for mode in ("granite", "bm25", "hybrid"):
        hits = retriever.search("cyber incident reporting", mode, k=3, filters=recent)
        assert {h.doc_id for h in hits} <= {"rbi-n12898"}
    only = Filters(kinds=["circular"])
    assert [
        h.doc_id for h in retriever.search("cyber incident reporting", "granite", 3, filters=only)
    ] == ["rbi-n12527"]
    one_doc = Filters(doc_ids=["rbi-n12715"])
    assert {h.doc_id for h in retriever.search("penal charges", "hybrid", 3, filters=one_doc)} == {
        "rbi-n12715"
    }


def test_an_unknown_mode_is_refused(retriever: Retriever) -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        retriever.search("penal charges", "colbert")


def test_point_ids_are_stable_so_reindexing_replaces() -> None:
    assert point_id("rbi-n1:section:0001") == point_id("rbi-n1:section:0001")
    assert point_id("rbi-n1:section:0001") != point_id("rbi-n1:section:0002")
