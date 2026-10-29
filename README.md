# FinScout AI

Give it a regulatory circular, as a web page or a PDF, and it writes an impact
assessment and an action plan for FlexiPay India, a fictional Indian fintech.
Four agents built with CrewAI do the work in sequence, all running on a local
Llama 3 8B model through Ollama, so the document is never sent to an outside
service. The report is a draft for a person to review; they then archive it as
approved or flag it for follow-up.

[`examples/sample_report.md`](examples/sample_report.md) is an unedited report
from the current code on the RBI's
[authentication directions for digital payments](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12898&Mode=0).
It shows both halves of the design. The assessment covers each of the
circular's five changes and finds one gap. It also marks cross-border payments
as not applying to FlexiPay while rating them High impact; the verification
agent passed that, the code checks caught it, and the report is marked
INCONSISTENT.

## The four agents

| Agent | Job | Tools |
| --- | --- | --- |
| Regulatory Interpreter | Reads the circular and summarises what changes, with paragraph numbers | A reader bound to the one document you chose (web page or PDF) |
| Business Impact Analyst | Decides, change by change, whether it applies to FlexiPay and what would have to change | Search over FlexiPay's internal policies in a Chroma vector database |
| Strategy and Compliance Advisor | Turns the assessment into a prioritised action plan | None |
| Verification Specialist | Checks the summary, the assessment and the plan against each other and gives a verdict | None |

Each agent has only the tool its job needs. Only the analyst can search the
policies, and only the interpreter can read the document.

## The checks around the agents

A small model left to itself will summarise a document it never opened, assess
the wrong subject, or rate a change as "does not apply" and "high impact" at
once. Every one of those has happened in a real run of this project. Code, not
a model, checks for them:

- The circular is fetched before any agent starts, so a page that is down or a
  missing browser stops the run in seconds with the real error.
- The summary is sent back if the reader tool was never called, if it copies
  the circular instead of summarising it, or if it lists no changes.
- The assessment is sent back if the analyst searched the knowledge base fewer
  than three times, if it is empty, if it leaves out a change the summary
  lists, or if its ratings contradict each other (a change that does not apply,
  or needs nothing, cannot have an impact).
- The plan is sent back if it both lists actions and says no changes are
  needed, or says nothing is needed when a change is rated.
- After two retries the answer is accepted, and the same checks run again on
  the finished report. If any fails, the verdict is INCONSISTENT whatever the
  verification agent said. The report header shows the code checks and the
  agent's own verdict side by side.
- Every knowledge-base search and what it returned is listed at the end of the
  report, so a reader can see what the assessment was based on.
- Documents longer than 12,000 characters are cut, and the report says so.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com).

```bash
git clone https://github.com/nihardamera/RegRadar.git
cd RegRadar
uv sync --extra v1
uv run playwright install chromium

ollama pull llama3:8b
ollama pull nomic-embed-text
```

The knowledge base (`knowledge_base/*.md`) is embedded with `nomic-embed-text`
on first use and stored in `chroma_db/`. It is rebuilt automatically when the
files change. `FINSCOUT_CHAT_MODEL` and `OLLAMA_BASE_URL` override the model
and the Ollama address.

## Run

```bash
uv run streamlit run app.py                        # web UI with the archive
uv run python cli.py "<circular URL or PDF path>" --out report.md
```

Without a CSS selector the reader keeps the page's main text and drops menus
and footers. On RBI notification pages `table.tablebg` selects just the
circular. On an Apple M4 laptop a run takes two to four minutes.

```bash
uv run pytest                  # the reading and checking code; no model needed
```

## Limitations

- The knowledge base describes a fictional company in six short documents. It
  shows how the retrieval works; it is not a real compliance corpus.
- The verifier only compares the three outputs with each other. It does not
  see the circular or the policies, so it can catch contradictions but not a
  summary that misreads the source.
- Llama 3 8B is a small model, and runs vary. The verification agent in
  particular is unreliable: it has passed an empty assessment, an assessment of
  the wrong subject, and contradictory ratings, which is why code checks
  decide the verdict. Treat every report as a first draft for a person.
- The coverage check is a word-overlap test. It catches an assessment of the
  wrong subject; it cannot judge whether a covered change was assessed well.
- It analyses one document per run, on demand. It does not monitor regulators'
  websites.
- The archive (SQLite) is a list of past reports with their status; it is not
  searchable.
