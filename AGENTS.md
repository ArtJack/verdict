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
  either file. A third checks the tester: `verdict-replay` runs each proven finding's
  `repro` command on a fresh detached checkout and writes `replays.jsonl`; `verdict-dupes`
  searches the tracker for each finding and writes `related.jsonl`; `verdict-check` asks a
  cheap model which other sites share each defect and writes leads to `reviews.jsonl`;
  `verdict-backfill` has the local model draft a repro for each old proven finding that has
  none, runs each draft in a sandbox, and keeps the ones that reproduce (`backfill.jsonl`).
- The cheap asked run: `verdict-run --lite`, a normal asked run under a $2.50 cap with the tester
  told its budget; measured level with plain Claude Code at the same budget on known defects.
  `verdict-run --escalate` (the local tier reads first and the tester works its list) located fewer.

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
  `filed.py` (findings as files), `sandbox.py` (the box every run of the project's own code
  goes through), `questions.py` (the questions ledger and
  `verdict-answer`), `accept.py`, `replay.py` (`verdict-replay`), `dupes.py` (`verdict-dupes`), `check.py` (`verdict-check`), `backfill.py` (`verdict-backfill`), `escalate.py` (`--escalate` packets), `readfirst.py`, `gate.py`, `runner.py` (headless runs), `browser.py` (`verdict-browse` and the
  profile's `site:` block: a site in a real browser, GET only, no model; its parts are the
  `browser_*` modules and `local_browser.py`), `server.py`
  (MCP); the guards `hooks/`; the state schema `docs/state-schema.md`; the evals
  `eval/`; the release notes `CHANGELOG.md` (one version line, three manifests).
- **A release** is a tag: `release.yml` builds, publishes to PyPI and the MCP registry,
  and writes the GitHub Release from the changelog. Bump `pyproject.toml`,
  `.claude-plugin/plugin.json` and `server.json` together.

## How we build

The maintainer's house rules for structure, the same in every repository. They live here so that every
agent sees them, wherever it runs. Where this repository's own rules are stricter, those win.

- **A new thing is a new file.** A new flow, integration, report or model task gets its own file in its
  feature's folder. A new source file stays under about 400 lines.
- **No source file over 2,000 lines grows, and none crosses that line.** A fix of up to 10 added lines may
  land in place. Anything larger goes into a new file, or follows an extraction of the part you are changing.
- **Refactoring is its own commit,** titled `refactor: …`. Nothing changes what the code does, tests change
  only to point at the new location, and the suite is green before and after. Code with no test gets a test
  of its current behaviour first. Where pull requests are squash-merged, the refactor is its own pull request.
- **Outside systems sit behind an interface** (a `Protocol` with only the methods the caller uses), built in
  one wiring module. No default argument builds a real client.
- **One shared fake per interface,** beside the real one: configurable, recording, with no business rules and
  no sleeps, and held to the real implementation by a contract test. New tests pass fakes in instead of
  patching the code's own modules by name.
- **A failure never looks like "empty" or "not checked",** and no error handler only logs or passes.
- **Tests land with the change.** A test named "clears" or "resets" asserts the dirty state first, and an
  expected value is never the production expression retyped.
- **Money is whole cents or `Decimal`,** never a float.
- **Check before you commit:** `python3 scripts/check_structure.py`. It fails when a source file crosses
  2,000 lines or one already over it grows by more than 10, and warns about the rest. CI runs it on every
  pull request and, for now, only reports.
