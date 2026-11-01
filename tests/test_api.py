"""The HTTP API, with fake retrieval and a scripted model (no Qdrant, no API)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from regradar.api import Services, app, services
from regradar.index import Hit
from regradar.llm import DryRun

TEXT = "Incidents shall be reported to RBI within 6 hours of detection."
HIT = Hit(
    "rbi-n1:section:0001",
    "rbi-n1",
    0,
    len(TEXT),
    1.0,
    {
        "title": "Cyber Directions",
        "text": TEXT,
        "page_url": "https://rbi.org.in/x",
        "date": "2024-07-30T00:00:00Z",
    },
)
META = {
    "rbi-n1": {"doc_id": "rbi-n1", "title": "Cyber Directions", "page_url": "https://rbi.org.in/x"}
}


def fake(reply: str | None = None, impact: object = None, dry: bool = False) -> Services:
    def generate(_system: str, _user: str) -> str:
        if dry:
            raise DryRun(0.001)
        assert reply is not None
        return reply

    return Services(
        search=lambda q, k, f: [HIT],
        generate=generate if (reply or dry) else None,
        impact=impact,  # type: ignore[arg-type]
        metadata=META,
        model="claude-haiku-5-5" if (reply or dry or impact) else None,
        spend=not dry,
        qdrant_ok=lambda: True,
    )


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(s: Services) -> None:
    app.dependency_overrides[services] = lambda: s


def test_health_and_metadata(client: TestClient) -> None:
    use(fake())
    assert client.get("/health").json() == {
        "status": "ok",
        "qdrant": True,
        "model": None,
        "spend": True,
    }
    assert client.get("/circulars/rbi-n1").json()["title"] == "Cyber Directions"
    assert client.get("/circulars/rbi-n999").status_code == 404


def test_search_returns_sources_with_urls(client: TestClient) -> None:
    use(fake())
    body = client.post("/search", json={"query": "incident reporting", "k": 3}).json()
    assert (
        body["hits"][0]["url"] == "https://rbi.org.in/x" and body["hits"][0]["date"] == "2024-07-30"
    )


def test_ask_returns_claims_with_their_sources(client: TestClient) -> None:
    reply = json.dumps(
        {
            "not_found": False,
            "claims": [{"text": "Report within 6 hours.", "citations": [HIT.chunk_id]}],
        }
    )
    use(fake(reply))
    body = client.post("/ask", json={"question": "How soon must incidents be reported?"}).json()
    assert body["status"] == "answered"
    assert body["claims"][0]["citations"][0]["title"] == "Cyber Directions"


def test_ask_refuses_an_answer_whose_citations_do_not_hold(client: TestClient) -> None:
    reply = json.dumps(
        {
            "not_found": False,
            "claims": [{"text": "Report within 2 hours.", "citations": [HIT.chunk_id]}],
        }
    )
    use(fake(reply))
    body = client.post("/ask", json={"question": "How soon must incidents be reported?"}).json()
    assert body["status"] == "rejected" and body["claims"] == [] and body["attempts"] == 2


def test_without_a_model_or_in_dry_run_the_model_endpoints_say_so(client: TestClient) -> None:
    use(fake())
    assert (
        client.post("/ask", json={"question": "How soon must incidents be reported?"}).status_code
        == 503
    )
    assert client.post("/impact", json={"doc_id": "rbi-n1"}).status_code == 503
    use(fake(dry=True))
    response = client.post("/ask", json={"question": "How soon must incidents be reported?"})
    assert response.status_code == 503 and "dry-run" in response.json()["detail"]


def test_impact_validates_the_circular(client: TestClient) -> None:
    use(fake(impact=lambda doc_id: {"doc_id": doc_id, "verdict": "no action needed"}))
    assert client.post("/impact", json={"doc_id": "rbi-n1"}).json()["verdict"] == "no action needed"
    assert client.post("/impact", json={"doc_id": "rbi-n404"}).status_code == 404
    assert client.post("/impact", json={"doc_id": "../etc"}).status_code == 422


def test_the_demo_rate_limit_is_per_visitor_and_per_day() -> None:
    from regradar.demo import RateLimit

    limits = RateLimit(per_visitor=(2, 600), per_day=3)
    assert limits.allow("a", now=0) is None and limits.allow("a", now=1) is None
    assert "limit reached" in (limits.allow("a", now=2) or "")
    assert limits.allow("a", now=700) is None  # the window has passed
    assert "daily" in (limits.allow("b", now=701) or "")
