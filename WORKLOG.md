# Work log

The plan is `03_REGRADAR.md` in `~/Desktop/portfolio/roadmap/`. A new chat
resumes from here: read the plan, then the latest entry below.

## 2026-10-30 (Fri): M0 baseline

**Done**
- Full-history gitleaks scan of FinScoutAI (11 commits): no leaks.
- Baseline at `06fa2a0` in a throwaway venv from `requirements.txt`:
  30 tests passed.
- Tagged `06fa2a0` as `finscout-v1` and pushed the tag. Renamed the GitHub
  repo FinScoutAI → RegRadar (the old URL redirects, 301). The local folder is
  now `repos/RegRadar`. All v2 work happens on branch `v2`; main keeps showing
  v1 until M6.
- uv + `pyproject.toml`. v1's pins are now the `v1` extra; `uv lock` resolved
  them together (198 packages). Dev tools: pytest 9.2.0, ruff 0.17.3,
  mypy 2.4.1 (strict, on `regradar/` only), pre-commit 4.7.0. ruff skips the
  v1 files so they stay as tagged until they are ported in M4. The only edit
  to v1 is a final newline the end-of-file hook added to three files.
- pre-commit (ruff, gitleaks v8.30.1, hygiene hooks) and GitHub Actions
  (checks + a gitleaks scan of the full history).
- README: a "being rebuilt" note and "History: started as FinScoutAI".

**Gotchas**
- Like Commit-Suggestor: the venv and data live in `.venv.nosync` /
  `data.nosync` behind symlinks, because iCloud syncs ~/Desktop.
- No global git identity is set on this Mac, so it is set per repo.
- Docker and Ollama are not installed. v1 cannot run end to end without
  Ollama, but no milestone needs it to: M4 compares against the committed
  `examples/sample_report.md`.

**Next**
1. Nihar: install OrbStack (or Docker Desktop) before M2, for Qdrant.
2. M1: check rbi.org.in's robots.txt and terms, then the polite, cached
   fetcher for ~300 circulars with metadata, a parse audit (text dropped,
   scanned PDFs), and ~20 synthetic policy documents. M1 gate after that.
