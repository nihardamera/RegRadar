"""A polite HTTP client: one request at a time, a pause between requests, and a
disk cache so nothing is downloaded twice.

RBI's own servers refuse automated clients (HTTP 418, or a JavaScript
challenge on rbidocs), so the corpus is read from the Internet Archive's
captures of rbi.org.in. The client says who it is in its User-Agent and does
not pretend to be a browser.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

USER_AGENT = "RegRadar/0.1 (research project; https://github.com/nihardamera/RegRadar)"

# The archive answers with this page, status 200 or 503, when it sheds load.
_OFFLINE_MARKER = b"Internet Archive services are temporarily offline"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A URL could not be fetched after every retry."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content_type: str
    body: bytes
    from_cache: bool


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class PoliteClient:
    """Fetches URLs no faster than one every `min_interval` seconds.

    Successful responses are cached under `cache_dir` (body plus a small JSON
    sidecar), keyed by the URL's SHA-256. A cached URL is never fetched again.
    """

    def __init__(
        self,
        cache_dir: Path,
        min_interval: float = 2.0,
        retries: int = 5,
        backoff: float = 15.0,
        timeout: float = 90.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.requests_made = 0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = cache_key(url)
        folder = self.cache_dir / key[:2]
        return folder / key, folder / f"{key}.json"

    def cached(self, url: str) -> Response | None:
        body_path, meta_path = self._paths(url)
        if not (body_path.exists() and meta_path.exists()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return Response(
            url=url,
            status=int(meta["status"]),
            content_type=str(meta["content_type"]),
            body=body_path.read_bytes(),
            from_cache=True,
        )

    def _store(self, response: Response) -> None:
        body_path, meta_path = self._paths(response.url)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(response.body)
        meta = {
            "url": response.url,
            "status": response.status,
            "content_type": response.content_type,
        }
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            remaining = self.min_interval - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def get(self, url: str) -> Response:
        """Return the URL's body, from the cache when possible.

        Retries on 429, 5xx, network errors and the archive's offline page,
        waiting `backoff`, then twice as long, and so on. A 404 or other
        client error is returned (and cached) rather than retried.
        """
        hit = self.cached(url)
        if hit is not None:
            return hit
        last_problem = "no attempt made"
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.backoff * 2 ** (attempt - 1))
            self._wait_turn()
            self.requests_made += 1
            try:
                reply = self._client.get(url)
            except httpx.HTTPError as error:
                last_problem = f"{type(error).__name__}: {error}"
                continue
            if reply.status_code in _RETRY_STATUSES or _OFFLINE_MARKER in reply.content[:4000]:
                last_problem = f"HTTP {reply.status_code}"
                continue
            response = Response(
                url=url,
                status=reply.status_code,
                content_type=reply.headers.get("content-type", ""),
                body=reply.content,
                from_cache=False,
            )
            self._store(response)
            return response
        raise FetchError(f"{url}: gave up after {self.retries + 1} attempts ({last_problem})")
