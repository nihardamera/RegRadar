"""A cached, budget-capped Claude client, for answers and the judge.

Nothing is sent unless `spend=True`: by default a call only estimates what it
would cost and raises `DryRun`, so a script can be pointed at the API and
priced before a cent is spent. Every response is cached on disk by model and
prompt, so a rerun (or CI) costs nothing, and every paid call is written to a
ledger. A call that could take total spend past `budget_usd` is refused
before it is sent.

The model has no default: choosing it is a decision, not a fallback. Claude
models take no `temperature`, so replies are not deterministic; the cache is
what makes a rerun reproducible.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "llm_cache"
BUDGET_USD = 5.00  # the project's whole API budget (WORKLOG, plan)

# USD per million tokens, input and output (Anthropic list prices, checked
# 2026-10-31 in the claude-api reference; Haiku 5.5's apply to prompts up to
# 100K tokens). Thinking tokens are billed as output.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# The JSON shape every answer must take (enforced by structured outputs; the
# checks in regradar.answer still run on whatever comes back).
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "not_found": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["not_found", "claims"],
    "additionalProperties": False,
}


class DryRun(RuntimeError):
    """Raised instead of sending a request when spending is not enabled."""

    def __init__(self, estimate_usd: float) -> None:
        super().__init__(f"dry run: this call would cost about ${estimate_usd:.4f}")
        self.estimate_usd = estimate_usd


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    """A deliberately high estimate (3 characters a token), for pricing ahead."""
    return len(text) // 3 + 1


@dataclass
class Ledger:
    path: Path

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def spent(self) -> float:
        return sum(float(e["usd"]) for e in self.entries())

    def add(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


class Claude:
    """`Generate` (system, user) -> text, over the Anthropic Messages API."""

    def __init__(
        self,
        model: str,
        purpose: str,
        spend: bool = False,
        schema: dict[str, Any] | None = None,
        effort: str = "low",
        max_tokens: int = 4000,
        budget_usd: float = BUDGET_USD,
        cache_dir: Path = CACHE,
        client: Any = None,
    ) -> None:
        if model not in PRICES:
            raise ValueError(f"no price on record for {model}; add it to PRICES first")
        self.model, self.purpose, self.spend = model, purpose, spend
        self.schema, self.effort, self.max_tokens = schema, effort, max_tokens
        self.budget_usd = budget_usd
        self.cache_dir = cache_dir
        self.ledger = Ledger(cache_dir / "ledger.jsonl")
        self._client = client
        # One client may be called from several threads: the budget check
        # reserves each call's worst case until its real cost is on the ledger.
        self._lock = threading.Lock()
        self._reserved = 0.0

    def _key(self, system: str, user: str | list[dict[str, str]]) -> str:
        raw = json.dumps([self.model, self.effort, self.schema, system, user], sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        price_in, price_out = PRICES[self.model]
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def estimate(self, system: str, user: str) -> float:
        """Worst-case cost of one uncached call (full output budget)."""
        return self.cost(estimate_tokens(system + user), self.max_tokens)

    def __call__(self, system: str, user: str) -> str:
        return self.chat(system, [{"role": "user", "content": user}])

    def chat(self, system: str, messages: list[dict[str, str]]) -> str:
        """A conversation (few-shot demonstrations arrive as earlier turns).

        A single user turn is keyed by its text alone, as before multi-turn
        calls existed, so earlier cached replies still match.
        """
        single = len(messages) == 1 and messages[0]["role"] == "user"
        user_text = "\n\n".join(m["content"] for m in messages)
        key = self._key(system, messages[0]["content"] if single else messages)
        cached = self.cache_dir / key[:2] / f"{key}.json"
        if cached.exists():
            text: str = json.loads(cached.read_text(encoding="utf-8"))["text"]
            return text
        estimate = self.estimate(system, user_text)
        if not self.spend:
            raise DryRun(estimate)
        with self._lock:
            spent = self.ledger.spent() + self._reserved
            if spent + estimate > self.budget_usd:
                raise BudgetExceeded(
                    f"${spent:.4f} spent or reserved; this call could cost ${estimate:.4f}, "
                    f"over the ${self.budget_usd:.2f} budget"
                )
            self._reserved += estimate
        try:
            response = self._send(system, messages)
        except BaseException:
            with self._lock:
                self._reserved -= estimate
            raise
        usd = self.cost(response.usage.input_tokens, response.usage.output_tokens)
        with self._lock:
            self._reserved -= estimate
            self.ledger.add(
                {
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": self.model,
                    "purpose": self.purpose,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "usd": round(usd, 6),
                    "key": key,
                }
            )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"the model declined: {response.stop_details}")
        text = next(block.text for block in response.content if block.type == "text")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"model": self.model, "text": text}), encoding="utf-8")
        return text

    def _send(self, system: str, messages: list[dict[str, str]]) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        output_config: dict[str, Any] = {"effort": self.effort}
        if self.schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": self.schema}
        return self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            output_config=output_config,
        )
