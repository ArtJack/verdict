# AGENTS.md — for agents that use Verdict, and agents that work on it

## If you are here to run Verdict on a repository

- **Claude Code:** install the plugin and run `/verdict:run`. The `verdict` agent
  (`agents/verdict.md`) is the contract; the hooks in `hooks/` enforce the read-only
  guarantee; the harness in `src/verdict_mcp/` measures.
- **Any other coding agent:** `npx skills add ArtJack/verdict` installs the five skills in
  `skills/` (release risk, verify a fix, flaky triage, root cause, spec review), and
  `pip install verdict-qa-mcp` gives you the harness commands they use:
  `verdict-facts` → your judgment (one file per finding under `<qa-root>/findings/`,
  plus `judgment.json`) → `verdict-finalize` → `verdict-gate`.
- Verdict **reports and specifies; it never fixes**. Route fixes to the implementer, then
  ask for the fix to be verified (`verdict-verify-fix`).
- The maintainer's two pens: `verdict-accept` (accept a finding's risk, with a citation)
  and `verdict-answer` (answer a question the tester parked). The tester cannot write
  either file.

## If you are here to change Verdict

- **Run the tests before anything else** and again before you hand off:
  `uv run pytest -q` (or `.venv/bin/python -m pytest -q`). Lint: `uv run --with ruff ruff check .`
- **The doctrine, in four rules.** Measured before modelled: a number the harness can
  compute is never left to the model (`docs/state-schema.md`). Every prompt change is
  eval-paid: `eval/run_eval.py` against a control (`--pair <git ref>`), results published
  in `eval/README.md` with the misses. Every fixed harness rule is pinned as a mutant the
  suite must kill: `eval/pinned_mutants.json`, checked by `eval/pin_check.py`. Reports to
  nobody; the ledger is published instead.
- **What costs money:** `eval/run_eval.py` and `verdict-run` launch model sessions. Do not
  run them without being asked.
- **Where things live:** the contract `agents/verdict.md`; the harness
  `src/verdict_mcp/harness.py` (facts, finalize, report), `validate.py` (the state
  contract, also the PostToolUse hook), `anchors.py` (cited lines, hashed; drift),
  `filed.py` (findings as files), `questions.py` (the questions ledger and
  `verdict-answer`), `accept.py`, `gate.py`, `runner.py` (headless runs), `server.py`
  (MCP); the guards `hooks/`; the state schema `docs/state-schema.md`; the evals
  `eval/`; the release notes `CHANGELOG.md` (one version line, three manifests).
- **A release** is a tag: `release.yml` builds, publishes to PyPI and the MCP registry,
  and writes the GitHub Release from the changelog. Bump `pyproject.toml`,
  `.claude-plugin/plugin.json` and `server.json` together.
