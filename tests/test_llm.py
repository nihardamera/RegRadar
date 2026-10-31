"""The paid client's guards, against a fake Anthropic client: nothing here
touches the network or needs a key."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from regradar.llm import ANSWER_SCHEMA, BudgetExceeded, Claude, DryRun


class FakeMessages:
    def __init__(
        self, text: str = '{"not_found": true, "claims": []}', stop: str = "end_turn"
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text, self.stop = text, stop

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop,
            stop_details=None,
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=2_000, output_tokens=400),
        )


def client(messages: FakeMessages) -> SimpleNamespace:
    return SimpleNamespace(messages=messages)


def test_nothing_is_sent_without_spend_and_the_cost_is_estimated(tmp_path: Path) -> None:
    fake = FakeMessages()
    llm = Claude("claude-haiku-5-5", "answer", cache_dir=tmp_path, client=client(fake))
    with pytest.raises(DryRun) as raised:
        llm("system", "user " * 100)
    assert fake.calls == [] and raised.value.estimate_usd > 0


def test_a_paid_call_is_cached_and_written_to_the_ledger(tmp_path: Path) -> None:
    fake = FakeMessages()
    llm = Claude(
        "claude-haiku-5-5",
        "answer",
        spend=True,
        schema=ANSWER_SCHEMA,
        cache_dir=tmp_path,
        client=client(fake),
    )
    first = llm("system", "question")
    second = llm("system", "question")
    assert first == second and len(fake.calls) == 1
    [entry] = llm.ledger.entries()
    # 2,000 in at $0.10/M + 400 out at $0.50/M
    assert entry["usd"] == pytest.approx(0.0004) and entry["purpose"] == "answer"
    sent = fake.calls[0]
    assert sent["output_config"]["format"]["schema"] == ANSWER_SCHEMA
    assert sent["output_config"]["effort"] == "low" and "temperature" not in sent


def test_a_call_that_could_break_the_budget_is_refused_before_it_is_sent(tmp_path: Path) -> None:
    fake = FakeMessages()
    llm = Claude(
        "claude-opus-5-5",
        "judge",
        spend=True,
        budget_usd=0.01,
        cache_dir=tmp_path,
        client=client(fake),
    )
    with pytest.raises(BudgetExceeded, match=r"over the \$0\.01 budget"):
        llm("system", "x" * 30_000)
    assert fake.calls == []


def test_spend_accumulates_across_clients_sharing_the_ledger(tmp_path: Path) -> None:
    fake = FakeMessages()
    for n in range(3):
        Claude("claude-haiku-5-5", "answer", spend=True, cache_dir=tmp_path, client=client(fake))(
            "s", f"q{n}"
        )
    assert Claude("claude-haiku-5-5", "judge", cache_dir=tmp_path).ledger.spent() == pytest.approx(
        0.0012
    )


def test_a_refusal_is_raised_not_returned(tmp_path: Path) -> None:
    llm = Claude(
        "claude-haiku-5-5",
        "answer",
        spend=True,
        cache_dir=tmp_path,
        client=client(FakeMessages(stop="refusal")),
    )
    with pytest.raises(RuntimeError, match="declined"):
        llm("system", "question")


def test_a_model_without_a_price_is_refused() -> None:
    with pytest.raises(ValueError, match="no price on record"):
        Claude("claude-unknown", "answer")
