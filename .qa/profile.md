---
gates:
  suite: uv run --group dev python -m pytest tests/
  fixture_freshness: python3 eval/fixture_freshness.py
test_ids_cmd: uv run --group dev python -m pytest tests/ --collect-only -q -o addopts=
test_one_cmd: uv run --group dev python -m pytest {id} -q -p no:cacheprovider -o addopts=
coverage_suite_cmd: uv run --group dev python -m coverage run -m pytest tests/ -q -o addopts=
---

# QA profile — verdict

Project-Key: verdict
Repo-Path: /Users/artjack/Projects/verdict
Repo-Remote: https://github.com/ArtJack/verdict
Mode: team (.qa/ committed with the repo)
Security-Pass: disabled
Created: 2026-08-28

## What this project is

The Verdict Claude Code plugin plus the `verdict-mcp` Python package (v0.12.0):

- `agents/verdict.md` — the QA agent's behaviour contract (the product).
- `hooks/` — `enforce_write_scope.py`, `enforce_bash_scope.py`, shared `qa_paths.py`.
  These are a **security control**: they are what makes "Verdict never patches your code"
  a guarantee rather than a promise.
- `src/verdict_mcp/` — read-only MCP server (`server.py`), CI gate (`gate.py`),
  project-key resolution (`project_key.py`), state IO (`state.py`).
- `eval/` — scorer (`score.py`), answer keys (`expected*.json`), regression corpus, and
  fixtures containing **intentionally seeded defects**.
- `action.yml` — the GitHub Action (gate mode, and experimental run mode).

## What it touches

No database, no network calls, no third-party accounts, no user data. It reads and writes
QA state under a `.qa/` directory or `$VERDICT_HOME`. The only privileged surfaces are:
the Action's `run` mode (installs npm packages, uses an API key, may commit `.qa/`), and
the hooks, which decide whether another agent's write is permitted.

## Isolation check

Pass when all three hold:

1. No network/DB/credential usage in the suite:
   `grep -rlE "requests\.|httpx|urlopen|boto3|psycopg|DATABASE_URL" tests/ src/` → no matches.
2. `pyproject.toml` has `testpaths = ["tests"]` — the seeded-defect fixtures under
   `eval/fixtures/` must never be collected by the project suite.
3. The suite writes only to pytest `tmp_path` and to hook-guarded QA roots.

## Forbidden commands

- No `git commit`, `git push`, `git checkout`, `git stash`, or any checkout mutation.
  QA reports; QA does not fix and does not commit. Committing `.qa/` is the maintainer's act.
- Never regenerate or "fix" `eval/fixtures/pricer-delta.diff`, the answer keys
  (`eval/expected*.json`), or the corpus. They are tamper-evidence and trust anchors.
- Never modify, skip, or xfail a test to make a gate green.
- Never `npm install -g` or run the Action's `run` mode locally — it uses
  `--dangerously-skip-permissions`.

## Real commands (from .github/workflows/ci.yml)

- Suite gate: `uv run --group dev python -m pytest tests/ -q`
  (CI matrix: ubuntu + windows x py3.10 + py3.13)
- **For counting**, use `uv run --group dev python -m pytest tests/` — the CI form yields
  `-qq` (see finding VERDICT-F-3) and prints no summary line.
- Test-ID collection: `uv run --group dev python -m pytest tests/ --collect-only -q -o addopts=`
- Fixture freshness gate: from `eval/fixtures/`,
  `git diff --no-index pricer pricer_rev_b > /tmp/fresh.diff || true; cmp pricer-delta.diff /tmp/fresh.diff`
- Self-gate: `verdict-gate .` (the repo gates itself via `.github/workflows/qa-gate.yml`,
  `max-age-hours: 240`).
- Changed-files coverage: `uv run --group dev python -m coverage run -m pytest tests/ -q -o addopts=`,
  named as `coverage_suite_cmd` in the front matter above and run by `verdict-facts` itself
  — the diff-coverage block in `state.json` is its output, not a declaration. Run 7 measured
  122 of 143 changed lines with it.
- Mutation testing: `mutmut` is in the dev group (`pyproject.toml`). No campaign has been
  run, so suite quality is unmeasured — which is a gap, not an absent tool.

## Known risk areas (weight effort here)

1. **Scope-guard hooks** — a bypass silently removes the product's core safety guarantee.
2. **Agent prompt** (`agents/verdict.md`) — the behaviour contract; regressions here are
   only visible through the eval corpus, not the unit suite.
3. **Scorer and answer keys** — if the scorer is wrong, every eval score is wrong.
4. **Gate exit codes** — a CI contract consumed by other repos; 0/1/3/4/5 are load-bearing.
5. **Cross-platform** — Windows is in the CI matrix but is not testable on this machine.

## Needs human decision

- Whether `.qa/` gets committed (required for the self-gate to work — VERDICT-F-2).
- Whether to add a coverage tool, and the changed-files coverage command if so.
- Risk acceptance for the Action's `run` mode (`--dangerously-skip-permissions` + bot commit).
