"""The polite client: pauses between requests, retries what is worth retrying,
and never downloads a URL twice. No network: httpx's MockTransport answers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from regradar.fetch import USER_AGENT, FetchError, PoliteClient


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds

    def clock(self) -> float:
        return self.now


def client(tmp_path: Path, handler: httpx.MockTransport, time: FakeTime) -> PoliteClient:
    return PoliteClient(
        tmp_path,
        min_interval=2.0,
        retries=2,
        backoff=10.0,
        transport=handler,
        sleep=time.sleep,
        clock=time.clock,
    )


def test_it_says_who_it_is_and_does_not_pose_as_a_browser(tmp_path: Path) -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, content=b"ok")

    with client(tmp_path, httpx.MockTransport(answer), FakeTime()) as polite:
        polite.get("https://web.archive.org/x")
    assert seen == [USER_AGENT]
    assert "Mozilla" not in USER_AGENT and "RegRadar" in USER_AGENT


def test_requests_are_spaced_out(tmp_path: Path) -> None:
    time = FakeTime()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok"))
    with client(tmp_path, transport, time) as polite:
        polite.get("https://example.org/a")
        polite.get("https://example.org/b")
        polite.get("https://example.org/c")
    assert time.sleeps == [2.0, 2.0]


def test_a_cached_url_is_not_fetched_again(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})

    time = FakeTime()
    with client(tmp_path, httpx.MockTransport(answer), time) as polite:
        first = polite.get("https://example.org/a.pdf")
    with client(tmp_path, httpx.MockTransport(answer), time) as polite:
        second = polite.get("https://example.org/a.pdf")
    assert calls == ["https://example.org/a.pdf"]
    assert second.from_cache and not first.from_cache
    assert second.body == b"%PDF-1.7" and second.content_type == "application/pdf"


def test_overload_and_the_archive_offline_page_are_retried_with_backoff(tmp_path: Path) -> None:
    replies = iter(
        [
            httpx.Response(429),
            httpx.Response(
                200, content=b"<p>Internet Archive services are temporarily offline.</p>"
            ),
            httpx.Response(200, content=b"the capture"),
        ]
    )
    time = FakeTime()
    with client(tmp_path, httpx.MockTransport(lambda request: next(replies)), time) as polite:
        assert polite.get("https://web.archive.org/x").body == b"the capture"
    assert 10.0 in time.sleeps and 20.0 in time.sleeps  # backoff doubles


def test_it_gives_up_with_the_last_reason(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with (
        client(tmp_path, transport, FakeTime()) as polite,
        pytest.raises(FetchError, match=r"3 attempts \(HTTP 503\)"),
    ):
        polite.get("https://web.archive.org/x")


def test_a_not_found_is_an_answer_not_a_retry(tmp_path: Path) -> None:
    calls: list[int] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with client(tmp_path, httpx.MockTransport(answer), FakeTime()) as polite:
        assert polite.get("https://example.org/gone").status == 404
    assert calls == [1]
