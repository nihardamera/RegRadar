"""DSPy, measured: the cited-answer step as a DSPy program, optimised and tested.

    uv run python -m regradar.optimize retrieve                 # fix the chunks per question
    uv run python -m regradar.optimize run --cap 2.00 --spend   # baseline, MIPROv2, GEPA, test

The program answers a golden question from its five retrieved chunks with
claims that cite them, and the same code checks as `regradar.answer` decide
whether the answer stands (one retry with the problems, then rejected).
Only the instructions and demonstrations change between programs; retrieval
and the checks do not, so a difference on test is the prompt's.

The metric needs no judge. It scores from the golden set: an unanswerable
question scores 1 for declining; an answerable one scores the mean of
citation recall (gold parts its citations cover) and citation precision
(citations that hold a gold span), and 0 when it declines or is rejected.
When retrieval missed the answer (no chunk holds gold text), declining scores
1: the context does not answer the question.
It also returns feedback in words (what was missed, which chunk had it,
which check failed), which GEPA reflects on.

Data: the 60 dev questions are split 30 / 30 into train and validation by a
hash of the ID; the 90 test questions are scored once per program at the
end. Task model Haiku 5.5; proposal and reflection model Sonnet 5.5. Every
call goes through `regradar.llm.Claude` (cache, ledger), and the run stops
at `--cap` dollars.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import dspy
from pydantic import BaseModel, Field

from regradar.answer import Claim, ContextChunk, Reply
from regradar.answer import problems as citation_problems
from regradar.evaluate import Retrieved, bootstrap_ci, overlaps, paired_difference_ci, part_found
from regradar.golden import Question, load
from regradar.llm import BudgetExceeded, Claude, Ledger

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "dspy"
RETRIEVAL = OUT / "retrieval.json"
TASK_MODEL = "claude-haiku-5-5"
REFLECTION_MODEL = "claude-sonnet-5-5"
K = 5

# The hand-written prompt (regradar.answer.SYSTEM), without its JSON layout,
# which the DSPy adapter supplies from the signature.
INSTRUCTIONS = """You answer questions about Reserve Bank of India circulars for a compliance team.
Use only the numbered context chunks you are given. Do not use outside knowledge.
Each claim is one sentence that answers part of the question, and cites the chunk IDs that
support it, copied exactly from the context. Copy numbers, amounts, dates and time limits
exactly as the chunk states them. If the context does not answer the question, set
not_found to true and give no claims. If feedback lists problems with a previous attempt,
fix them."""


# --- the model, behind DSPy's engine interface ------------------------------------


class ClaudeEngine:
    """DSPy 3.4 engine (complete(Request) -> Response) over our cached, capped client."""

    def __init__(self, claude: Claude) -> None:
        self.claude = claude
        # Set when a call is refused for budget, so a run can tell that the
        # optimiser scored refusals as failures, and stop instead of reporting.
        self.exhausted = False

    def complete(self, request: Any) -> Any:
        from dspy.lm15 import Message, Response, TextPart, Usage

        system = request.system
        if system is not None and not isinstance(system, str):
            system = "".join(getattr(part, "text", "") for part in system)
        messages = [{"role": m.role, "content": m.text or ""} for m in request.messages]
        try:
            text = self.claude.chat(system or "", messages)
        except BudgetExceeded:
            self.exhausted = True
            raise
        return Response(
            id=None,
            model=self.claude.model,
            message=Message.assistant([TextPart(text)]),
            finish_reason="stop",
            usage=Usage(input_tokens=None, output_tokens=None, total_tokens=None),
        )

    def stream(self, request: Any) -> Any:
        from dspy.lm15 import response_to_events

        return response_to_events(self.complete(request))

    def close(self) -> None:
        pass


def lm(model: str, purpose: str, spend: bool, cap: float, effort: str = "low") -> dspy.LM:
    claude = Claude(model, purpose, spend=spend, effort=effort, max_tokens=4000, budget_usd=cap)
    # DSPy's own cache is off: ours is keyed by the prompt and feeds the ledger.
    return dspy.LM(f"anthropic/{model}", engine=ClaudeEngine(claude), cache=False)


# --- the program --------------------------------------------------------------------


class ClaimOut(BaseModel):
    text: str = Field(description="one sentence")
    citations: list[str] = Field(description="chunk IDs copied exactly from the context")


class CitedAnswer(dspy.Signature):
    __doc__ = INSTRUCTIONS

    question: str = dspy.InputField()
    context: str = dspy.InputField(desc="numbered chunks: [chunk id] title, then text")
    feedback: str = dspy.InputField(desc="problems with a previous attempt, or 'none'")
    not_found: bool = dspy.OutputField()
    claims: list[ClaimOut] = dspy.OutputField()


def context_text(chunks: list[ContextChunk]) -> str:
    return "\n\n".join(f"[{c.chunk_id}] {c.title}\n{c.text}" for c in chunks)


class CitedAnswerer(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.answer = dspy.Predict(CitedAnswer)

    def forward(self, question: str, chunks: list[ContextChunk]) -> dspy.Prediction:
        feedback, found, reply = "none", ["not attempted"], None
        for attempt in (1, 2):  # noqa: B007 (reported after the loop)
            try:
                out = self.answer(
                    question=question, context=context_text(chunks), feedback=feedback
                )
                reply = Reply(
                    not_found=bool(out.not_found),
                    claims=[
                        Claim.model_validate(c.model_dump() if isinstance(c, BaseModel) else c)
                        for c in out.claims or []
                    ],
                )
                found = citation_problems(reply, chunks, question)
            except Exception as error:  # an unparseable reply is a problem like any other
                if type(error).__name__ in ("BudgetExceeded", "DryRun"):
                    raise
                reply, found = None, [f"reply not in the required format: {str(error)[:200]}"]
            if not found:
                break
            feedback = "\n".join(f"- {p}" for p in found)
        if found or reply is None:
            return dspy.Prediction(status="rejected", claims=[], problems=found, attempts=attempt)
        status = "not_found" if reply.not_found else "answered"
        claims = [c.model_dump() for c in reply.claims]
        return dspy.Prediction(status=status, claims=claims, problems=[], attempts=attempt)


# --- the metric -----------------------------------------------------------------------


def score(question: Question, retrieved: list[Retrieved], pred: Any) -> tuple[float, str]:
    """Score in [0, 1] and feedback in words, from the golden set alone."""
    by_id = {r.chunk_id: r for r in retrieved}
    holding = [r.chunk_id for r in retrieved if any(overlaps(r, s) for s in question.spans)]
    if not question.answerable:
        if pred.status != "answered":
            return 1.0, "Correct: the context does not answer this, and the answer declined."
        return 0.0, (
            "Wrong: none of the chunks answers this question (it is outside the corpus), "
            "but the answer made claims. It should have set not_found."
        )
    if not holding:
        # Retrieval missed the answer: from this context, declining is right.
        if pred.status != "answered":
            return 1.0, "Correct: none of the chunks holds the answer, and the answer declined."
        return 0.0, (
            "Wrong: none of the chunks holds the answer to this question, but the answer "
            "made claims. It should have set not_found."
        )
    if pred.status == "rejected":
        return 0.0, "Rejected by the citation checks: " + "; ".join(pred.problems)
    if pred.status == "not_found":
        return 0.0, f"Wrong: said not found, but chunk(s) {', '.join(holding)} answer it."
    cited_ids = list(dict.fromkeys(cid for c in pred.claims for cid in c["citations"]))
    cited = [by_id[c] for c in cited_ids if c in by_id]
    precision = sum(any(overlaps(c, s) for s in question.spans) for c in cited) / max(1, len(cited))
    found = [part_found(cited, part) for part in question.gold]
    recall = sum(found) / len(found)
    notes = []
    missed = [p for p, ok in zip(question.gold, found, strict=True) if not ok]
    if missed:
        quote = missed[0].spans[0].quote
        notes.append(
            f'Missed {len(missed)} of {len(found)} parts of the answer, e.g. "{quote[:160]}".'
        )
        notes.append(f"Chunks holding answer text: {', '.join(holding)}.")
    stray = [c.chunk_id for c in cited if not any(overlaps(c, s) for s in question.spans)]
    if stray:
        notes.append(f"Cited chunk(s) without answer text: {', '.join(stray)}.")
    value = (recall + precision) / 2
    return value, " ".join(notes) or "Correct and fully cited."


def metric(
    gold: dspy.Example, pred: Any, trace: Any = None, pred_name: Any = None, pred_trace: Any = None
) -> Any:
    value, feedback = score(gold.question_obj, gold.retrieved, pred)
    return dspy.Prediction(score=value, feedback=feedback)


def numeric_metric(gold: dspy.Example, pred: Any, trace: Any = None) -> float:
    value, _ = score(gold.question_obj, gold.retrieved, pred)
    # MIPROv2 keeps a bootstrapped demonstration only when this is truthy.
    return value if trace is None else float(value >= 0.75)


# --- data -------------------------------------------------------------------------


def cmd_retrieve(_args: argparse.Namespace) -> int:
    from regradar.evaluate import Config
    from regradar.evaluate_answers import qdrant_retrieve

    retrieve = qdrant_retrieve(Config("section", "hybrid"), K)
    out = {}
    for q in load():
        out[q.id] = [
            {"retrieved": asdict(r), "title": c.title, "text": c.text} for r, c in retrieve(q)
        ]
    OUT.mkdir(parents=True, exist_ok=True)
    RETRIEVAL.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} questions -> {RETRIEVAL}")
    return 0


def examples() -> tuple[list[dspy.Example], list[dspy.Example], list[dspy.Example]]:
    stored = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    train, val, test = [], [], []
    for q in load():
        rows = stored[q.id]
        ex = dspy.Example(
            question=q.question,
            chunks=[ContextChunk(r["retrieved"]["chunk_id"], r["title"], r["text"]) for r in rows],
            question_obj=q,
            retrieved=[Retrieved(**r["retrieved"]) for r in rows],
        ).with_inputs("question", "chunks")
        if q.split == "test":
            test.append(ex)
        elif int(hashlib.sha256(f"dspy:{q.id}".encode()).hexdigest(), 16) % 2:
            train.append(ex)
        else:
            val.append(ex)
    return train, val, test


# --- the run --------------------------------------------------------------------------


def evaluate(program: dspy.Module, data: list[dspy.Example], threads: int = 6) -> list[float]:
    from concurrent.futures import ThreadPoolExecutor

    def one(ex: dspy.Example) -> float:
        return score(
            ex.question_obj, ex.retrieved, program(question=ex.question, chunks=ex.chunks)
        )[0]

    with ThreadPoolExecutor(threads) as pool:
        return list(pool.map(one, data))


def cmd_run(args: argparse.Namespace) -> int:
    ledger = Ledger(ROOT / "data" / "llm_cache" / "ledger.jsonl")
    start = ledger.spent()
    cap = start + args.cap
    task = lm(TASK_MODEL, "dspy-task", args.spend, cap)
    reflect = lm(REFLECTION_MODEL, "dspy-reflect", args.spend, cap, effort="medium")
    engines = [task.engine, reflect.engine] if hasattr(task, "engine") else []
    dspy.configure(lm=task, adapter=dspy.ChatAdapter())
    train, val, test = examples()
    OUT.mkdir(parents=True, exist_ok=True)
    results_path = ROOT / "eval" / "results" / "dspy_test.json"
    result: dict[str, Any] = {
        "task_model": TASK_MODEL,
        "reflection_model": REFLECTION_MODEL,
        "cap_usd": args.cap,
        "n": {"train": len(train), "val": len(val), "test": len(test)},
        "optimisation_cost_usd": {},
        "evaluation_cost_usd": {},
        "programs": {},
        "paired_test_differences": {},
        "complete": False,
    }
    scores: dict[str, list[float]] = {}

    def save() -> None:
        result["total_cost_usd"] = round(ledger.spent() - start, 4)
        results_path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")

    def exhausted() -> bool:
        return any(getattr(e, "exhausted", False) for e in engines)

    def record(name: str, program: dspy.Module) -> None:
        mark = ledger.spent()
        program.save(str(OUT / f"{name}.json"))
        val_scores, test_scores = evaluate(program, val), evaluate(program, test)
        result["evaluation_cost_usd"][name] = round(ledger.spent() - mark, 4)
        scores[name] = test_scores
        result["programs"][name] = {
            "val": bootstrap_ci(val_scores),
            "test": bootstrap_ci(test_scores),
            "test_scores": test_scores,
        }
        if name != "baseline":
            result["paired_test_differences"][f"{name} - baseline"] = paired_difference_ci(
                scores["baseline"], test_scores
            )
        save()
        print(f"{name}: test {result['programs'][name]['test']}", file=sys.stderr)

    baseline = CitedAnswerer()
    record("baseline", baseline)
    optimisers: list[tuple[str, Any]] = [
        (
            "mipro",
            dspy.MIPROv2(
                metric=numeric_metric,
                prompt_model=reflect,
                task_model=task,
                auto="light",
                max_bootstrapped_demos=2,
                max_labeled_demos=0,
                num_threads=6,
                seed=20261102,
            ),
        ),
        (
            "gepa",
            dspy.GEPA(
                metric=metric,
                reflection_lm=reflect,
                max_metric_calls=args.gepa_calls,
                num_threads=6,
                track_stats=True,
                seed=20261102,
            ),
        ),
    ]
    for name, optimiser in optimisers:
        mark = ledger.spent()
        compiled = optimiser.compile(baseline.deepcopy(), trainset=train, valset=val)
        result["optimisation_cost_usd"][name] = round(ledger.spent() - mark, 4)
        if exhausted():
            result["stopped"] = f"the ${args.cap:.2f} cap was reached during {name}"
            save()
            print(result["stopped"], file=sys.stderr)
            return 1
        record(name, compiled)
    result["complete"] = True
    save()
    summary = {k: v["test"] for k, v in result["programs"].items()}
    keys = ("paired_test_differences", "optimisation_cost_usd", "total_cost_usd")
    print(json.dumps({"test": summary, **{k: result[k] for k in keys}}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("retrieve").set_defaults(run=cmd_retrieve)
    run = steps.add_parser("run")
    run.add_argument("--cap", type=float, required=True, help="dollars this run may spend")
    run.add_argument("--gepa-calls", type=int, default=200)
    run.add_argument("--spend", action="store_true")
    run.set_defaults(run=cmd_run)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
