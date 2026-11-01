"""The HTTP API: search, cited answers, and impact reports.

    REGRADAR_MODEL=claude-haiku-5-5 REGRADAR_SPEND=1 uv run uvicorn regradar.api:app

    GET  /health                  Qdrant reachable, which model, whether it may spend
    GET  /circulars/{doc_id}      a circular's metadata and source URLs
    POST /search                  hybrid retrieval with filters (no model call)
    POST /ask                     an answer whose every claim cites a chunk, or "not found"
    POST /impact                  obligations, gaps against the policies, an action plan

The model is set by `REGRADAR_MODEL`; there is no default. Without
`REGRADAR_SPEND=1` the model runs in dry-run mode and /ask and /impact answer
only from the response cache. Services are built once, on first use, and can
be replaced (the tests use fakes).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from regradar import __version__
from regradar.answer import ContextChunk, Generate, answer
from regradar.index import Filters, Hit
from regradar.llm import BudgetExceeded, DryRun

app = FastAPI(
    title="RegRadar",
    version=__version__,
    description="Cited answers and impact reports over RBI circulars. Every answer is a draft "
    "for human review; the company in impact reports is synthetic.",
)


@dataclass
class Services:
    search: Callable[[str, int, Filters | None], list[Hit]]
    generate: Generate | None  # None when no model is configured
    impact: Callable[[str], dict[str, Any]] | None
    metadata: dict[str, dict[str, Any]]
    model: str | None
    spend: bool
    qdrant_ok: Callable[[], bool]


@lru_cache(maxsize=1)
def services() -> Services:
    from regradar.impact import analyse, markdown, to_json
    from regradar.index import Retriever, connect, metadata
    from regradar.llm import ANSWER_SCHEMA, Claude

    client = connect()
    retriever = Retriever(client, "section")
    model = os.environ.get("REGRADAR_MODEL") or None
    spend = os.environ.get("REGRADAR_SPEND") == "1"

    def search(query: str, k: int, filters: Filters | None) -> list[Hit]:
        return retriever.search(query, mode="hybrid", k=k, filters=filters)

    def impact(doc_id: str) -> dict[str, Any]:
        assert model is not None
        report = analyse(doc_id, model, spend, client, retriever.encoders)
        return {**to_json(report), "markdown": markdown(report)}

    def qdrant_ok() -> bool:
        try:
            client.get_collections()
            return True
        except Exception:
            return False

    generate = Claude(model, "api-answer", spend=spend, schema=ANSWER_SCHEMA) if model else None
    return Services(
        search, generate, impact if model else None, metadata(), model, spend, qdrant_ok
    )


ServicesDep = Annotated[Services, Depends(services)]


class FilterIn(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    kinds: list[str] = Field(default_factory=list, description='e.g. ["directions"]')
    doc_ids: list[str] = Field(default_factory=list)
    circular_number: str | None = None

    def to_filters(self) -> Filters:
        return Filters(
            date_from=self.date_from,
            date_to=self.date_to,
            kinds=self.kinds,
            doc_ids=self.doc_ids,
            circular_number=self.circular_number,
        )


class SearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    k: int = Field(10, ge=1, le=50)
    filters: FilterIn | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    k: int = Field(5, ge=1, le=10)
    filters: FilterIn | None = None


class ImpactIn(BaseModel):
    doc_id: str = Field(pattern=r"^rbi-[a-z0-9]+$")


def _source(hit: Hit) -> dict[str, Any]:
    p = hit.payload
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "title": p.get("title"),
        "circular_number": p.get("circular_number"),
        "date": (p.get("date") or "")[:10] or None,
        "section": p.get("section"),
        "page": p.get("page"),
        "url": p.get("page_url"),
    }


def _model_error(error: Exception) -> HTTPException:
    if isinstance(error, DryRun):
        return HTTPException(503, "the model is in dry-run mode and this request is not cached")
    return HTTPException(503, f"the API budget would be exceeded: {error}")


@app.get("/health")
def health(s: ServicesDep) -> dict[str, Any]:
    return {"status": "ok", "qdrant": s.qdrant_ok(), "model": s.model, "spend": s.spend}


@app.get("/circulars/{doc_id}")
def circular(doc_id: str, s: ServicesDep) -> dict[str, Any]:
    meta = s.metadata.get(doc_id)
    if meta is None:
        raise HTTPException(404, f"{doc_id} is not in the corpus")
    keys = ("doc_id", "title", "circular_number", "date", "department", "kind", "pages")
    # The RBI's own URLs, and the Internet Archive copies the text was taken from.
    urls = ("page_url", "pdf_url", "page_capture_url", "pdf_capture_url")
    return {k: meta.get(k) for k in (*keys, *urls)}


@app.post("/search")
def search(body: SearchIn, s: ServicesDep) -> dict[str, Any]:
    filters = body.filters.to_filters() if body.filters else None
    hits = s.search(body.query, body.k, filters)
    return {"hits": [_source(h) | {"text": h.payload.get("text")} for h in hits]}


@app.post("/ask")
def ask(body: AskIn, s: ServicesDep) -> dict[str, Any]:
    if s.generate is None:
        raise HTTPException(503, "no model configured (set REGRADAR_MODEL)")
    filters = body.filters.to_filters() if body.filters else None
    hits = s.search(body.question, body.k, filters)
    chunks = [ContextChunk(h.chunk_id, h.payload["title"], h.payload["text"]) for h in hits]
    try:
        result = answer(body.question, chunks, s.generate)
    except (DryRun, BudgetExceeded) as error:
        raise _model_error(error) from error
    sources = {h.chunk_id: _source(h) for h in hits}
    return {
        "status": result.status,
        "answer": result.text,
        "claims": [
            {"text": c.text, "citations": [sources[cid] for cid in c.citations]}
            for c in result.claims
        ]
        if result.status == "answered"
        else [],
        "problems": result.problems,
        "attempts": result.attempts,
    }


@app.post("/impact")
def impact(body: ImpactIn, s: ServicesDep) -> dict[str, Any]:
    if s.impact is None:
        raise HTTPException(503, "no model configured (set REGRADAR_MODEL)")
    if body.doc_id not in s.metadata:
        raise HTTPException(404, f"{body.doc_id} is not in the corpus")
    try:
        return s.impact(body.doc_id)
    except (DryRun, BudgetExceeded) as error:
        raise _model_error(error) from error
