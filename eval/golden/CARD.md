# Golden set: card

**What it is.** Questions about the RBI corpus ([`../../corpus/`](../../corpus/CARD.md)),
each with a reference answer and the exact text that answers it, in
[`questions.jsonl`](questions.jsonl). It measures retrieval (does the system
find the text?) and answers (does it say what the text says, and cite it?).

**Who wrote it.** Drafted by Claude Code (claude-opus-5-5), at Nihar Damera's
request, on 31 Oct 2026; every record says so in `author`. Human review is
recorded per question (`reviewed_by`, `reviewed`); `check` reports how many have
been reviewed. Until a question is reviewed, treat it as a careful draft.
No question, answer or span came from RegRadar's retriever: answers were
located with plain keyword search, and retrieval was not run until the set was
complete.

**Status.** v1: 150 questions, complete. Human review: a random sample of 30
(`review --sample 30 --seed 1`) reviewed by Nihar Damera on 2 Nov 2026: 28
approved, 2 flagged. Both flags were resolved without changing the set: q098 is
unanswerable by design ("not found" is the expected answer), and q127 asks only
about low-risk customers, so the high-risk timeline is out of scope. The flags and
resolutions are in each record's `notes`. The other 120 are unreviewed drafts.

## How v1 was drafted

1. **Documents by stratified random sample** (department x period, seed
   20261031), not chosen by familiarity; random sections of each were read and
   questions written from them. Near-identical UAPA sanctions-list updates were
   capped.
2. **Every quote verified** against the cleaned text (`locate`), and every
   question written as an analyst would ask it (31% of question words appear in
   the gold quotes).
3. **Restatements**: exact-text matches in other documents were added only for
   quotes of 12+ words (short phrases recur in unrelated rules); a word-overlap
   scan then found 80 reworded candidates, of which 44 were accepted by hand.
   Rejected: a different kind of entity (an NBFC question is not answered by
   the CIC version), a question that names one instrument or period, and same
   words in a different rule.
4. **Current law.** Where a 2025-26 consolidated Direction restates an older
   rule, it is an alternative span; a question that names an older instrument
   accepts only that instrument.
5. **Unanswerable questions** were each checked with several keyword searches
   that must match nothing; the searches are listed in the question's notes.
   Mix: rules of other regulators (SEBI, IRDAI, PFRDA), enforcement actions,
   future decisions, tax, and near-domain details the corpus is silent on.

## Known issues

- **Model-written questions.** A Claude model wrote the set. If the answer model
  is also a Claude model, the shared style may make questions easier for it;
  the answer model is chosen with that in mind, and results say which was used.
- **Withdrawn instruments.** Some gold spans are in circulars RBI withdrew in the
  November 2025 consolidation (marked "Withdrawn" in their text); where the
  current Direction restates the rule it is an alternative.
- **Strike-through.** q141's circular marks an amendment with strike-through;
  extracted text keeps both the deleted and inserted words ("shall may").
- A few footers survive cleaning (`Tel.No.` without a space); fixing the
  cleaner moves offsets, so it waits for a planned re-index.

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

These were the rules for writing; they apply to any question added later.

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
| v1 | 2026-10-31 | 150 | complete: 50 single-hop, 25 multi-hop, 30 number/date, 15 identifier, 30 unanswerable; 60 dev, 90 test; drafted by Claude Code; random 30 reviewed by Nihar Damera (28 approved, 2 flags resolved) |
