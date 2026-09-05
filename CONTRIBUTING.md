# Contributing

Verdict is a QA agent, so the bar for a change is the bar it holds everyone else to:
say what you measured, cite it, and leave the tree the way a stranger can reproduce.

## The short version

- **Run the suite before and after.** `uv run --group dev pytest -q`. It is fast (about
  80 seconds) and it is the contract — the eval fixtures under `eval/fixtures/` contain
  seeded defects on purpose and are excluded from collection.
- **A rule needs a test that can fail.** Put the defect back and watch the test go red
  before you trust it. If the rule is worth pinning, add its mutant to
  [`eval/pinned_mutants.json`](eval/pinned_mutants.json) and run
  `uv run python eval/pin_check.py --filter <your label>` — every entry runs against the
  whole suite, and a survivor is a rule nothing defends.
- **Lint is narrow on purpose.** `uv run --with ruff ruff check .` — correctness rules only;
  the narrative comment style is a house idiom, not mess, so `ruff format` is not run.
- **The prompt is eval-paid.** Any edit to [`agents/verdict.md`](agents/verdict.md) or a
  command file changes behaviour, and behaviour is measured: run the relevant fixture
  through [`eval/run_eval.py`](eval/run_eval.py) at n≥3 against a byte-identical control
  and publish the scores in [`eval/README.md`](eval/README.md), misses included. A
  prompt change without a measurement will be asked for one.
- **Versions move together.** `pyproject.toml`, `.claude-plugin/plugin.json` and
  `server.json` carry one version; `tests/test_versions.py` refuses a commit where they
  disagree, and `release.yml` refuses a tag that disagrees with them.
- **Every change gets a CHANGELOG entry** in the existing voice: what was wrong, what was
  measured, what is deliberately not in the release.

## What is welcome

- A finding against Verdict itself. Run `/verdict:run` on this repository or on your own
  and file what it gets wrong — the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml)
  asks for the evidence the way the agent would.
- An independent eval result, including a miss — the
  [eval result template](.github/ISSUE_TEMPLATE/eval_result.yml) exists for exactly that.
- A fixture in another language or runner. `eval/fixtures/pricer-ts` is the model: the same
  seeded defects, idiomatic to the ecosystem, with an answer key.
- A case study of a real run on a real project, with what it caught and what it missed.

## What is not

- A fix applied by the agent to the code it judges. Verdict reports; it never patches.
  That line is structural and stays.
- A check that cannot fail. If the test passes with the rule deleted, it is not a test.
- A published number without the script that produced it beside it.

## Where things are

| Path | What |
|---|---|
| `agents/verdict.md` | the agent's contract — the prompt |
| `commands/` | the ten `/verdict:*` commands |
| `hooks/` | the scope guards, the state validator hook, the session banner |
| `src/verdict_mcp/` | the harness (`facts` → `finalize`), the gate, the MCP server, the CLIs |
| `eval/` | fixtures, scorer, mutation tools, published results |
| `tests/` | the suite; `tests/test_agent_contract.py` is the free half of prompt coverage |
| `.qa/` | Verdict's own QA state, in team mode — every release is audited by the tool |
| `docs/state-schema.md` | the state contract |

Questions go in an issue. There is no chat.
