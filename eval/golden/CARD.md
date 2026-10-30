# Golden set: card

**What it is.** Questions about the RBI corpus ([`../../corpus/`](../../corpus/CARD.md)),
each with a reference answer and the exact text that answers it, in
[`questions.jsonl`](questions.jsonl). It measures retrieval (does the system
find the text?) and answers (does it say what the text says, and cite it?).

**Who writes it.** Nihar Damera, by hand. No question, answer or span comes from
a model RegRadar evaluates, or from RegRadar's retriever: answers are located
with plain keyword search (`find`), so the set does not lean toward what the
system already finds.

**Status.** Being written. Target: 150 questions.

## Make-up

| Type | Target | What it tests |
| --- | --- | --- |
| `single_hop` | 50 | One passage answers it |
| `multi_hop` | 25 | Two or more passages are needed (two circulars, or a rule and its exception) |
| `number_or_date` | 30 | The answer is a number, limit, period or date (6 hours, 5 per cent, 25 crore) |
| `identifier` | 15 | The question names a circular or paragraph ("What does RBI/2025-26/79 require of issuers?") |
| `unanswerable` | 30 | The corpus does not answer it; the right reply is "not found in the corpus" |

## How an answer is recorded

- A gold answer is a list of **parts**, all needed (one part for single-hop,
  two or more for multi-hop). Each part lists one or more **spans**, any of
  which will do: the same rule is often restated in later circulars or the
  2025 consolidated Directions, and retrieving either is correct. When a span
  is added, the tool finds the same words in other documents and asks
  whether each is equally correct.
- A span is a quote from the cleaned text with its character range, so one set
  scores every chunking strategy: a retrieved chunk counts when it overlaps a
  span. A test fails if a change to the cleaner moves a quote.
- The dev/test split is fixed by the question's ID when it is written (about a
  third dev). Dev is for tuning (prompts, thresholds, DSPy); test is looked
  at only for the final numbers.

## Writing guidance

1. **Ask as a compliance analyst at a payments company or NBFC would**, in
   your own words. Questions copied from a circular's wording favour keyword
   search; `check` reports how much each question borrows from its quote.
   Some identifier questions are meant to use exact tokens.
2. **One question, one thing to find.** "What are the KFS rules?" has no
   precise answer; "Must a KFS be given for a ₹5,000 digital loan?" has.
3. **Quote the shortest passage that fully answers it.** Usually a sentence
   or two, not a whole paragraph.
4. **Current law.** When a rule was replaced, the gold is the current text.
   Accept an older restatement as an alternative only if it says the same
   thing, and say so in the notes.
5. **Unanswerable questions** should be plausible, not absurd. Kinds to mix:
   a topic the corpus does not cover (insurance, securities: SEBI or IRDAI
   rules); a rule that does not exist ("What is the maximum PPI balance for
   minors?", if no corpus document sets one); a false premise ("Since RBI
   banned UPI for NBFCs in 2024, ..."); a detail the corpus is silent on.
   Check with `find` that the corpus really does not answer it.
6. **Use `sample`** to see circulars no question covers yet, so the set is not
   built from the documents you already know.
7. **Don't run RegRadar's search while writing**, and don't look at retrieval
   results until the set is frozen.

## Commands

```bash
uv run python -m regradar.golden sample            # circulars to write about
uv run python -m regradar.golden find "penal charges capitalisation"
uv run python -m regradar.golden add               # one question at a time
uv run python -m regradar.golden check             # validate, and progress by type
```

## Versioning

v1 is frozen when it reaches 150 questions and `check` reports no problems;
the commit that freezes it is recorded here. Later fixes (a wrong span, a
question that turns out ambiguous) are logged below with the reason, and
results state which version they used.

| Version | Date | Questions | Change |
| --- | --- | --- | --- |
| v1 (draft) | — | 0 | being written |
