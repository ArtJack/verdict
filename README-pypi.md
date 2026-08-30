# verdict-qa-mcp

**A read-only MCP server and release gate over [Verdict](https://github.com/ArtJack/verdict)'s
QA state — so anything that speaks MCP can consult your QA memory.**

Verdict is a Claude Code QA agent that keeps a baseline and reports what broke since
yesterday: findings with stable IDs and ages, every red test classified, flaky tests
quarantined *with an expiry*, and a verdict of `pass | pass with risks | blocked | fail`
that names what was **not** tested.

This distribution is the part of Verdict that other tools talk to. It reads the same state
files the agent writes and never writes to them — an orchestrator gating a merge, a Cursor
or Codex session, or a CI step commenting on a PR can all ask what the tester last found.
The agent itself is a Claude Code plugin with zero dependencies and works without this
package.

> **Note on the name.** The distribution is `verdict-qa-mcp`; the console script is still
> `verdict-mcp`, and the import package is still `verdict_mcp`. `verdict-mcp` was taken on
> PyPI by an unrelated project.

## Install

```
claude mcp add verdict -- uvx --from verdict-qa-mcp verdict-mcp
```

Or `pip install verdict-qa-mcp` / `uv pip install verdict-qa-mcp`.

## MCP tools

Every tool carries a read-only annotation, and the server never writes — the tester's
memory is public API; the tester's pen is not.

| Tool | Returns |
|---|---|
| `get_verdict(project)` | last verdict, release blockers, report path, not-tested list |
| `get_findings(project, status)` | `open` (default), `all`, or `NEW / STILL_OPEN / RESOLVED / REGRESSED` — REGRESSED ranked first |
| `get_quarantine(project)` | the flaky ledger, each entry with a computed `expired` flag |
| `get_history(project)` | run-over-run trend parsed from the report index |
| `get_report(project, report?)` | full report content, path-guarded to the QA root — so CI can quote the evidence, not just link it |
| `get_profile(project)` | isolation rules, risk areas, real test commands, and the lessons ledger when one exists |
| `get_trends(project)` | trajectory, current pressure (open by severity, age, quarantine size), and **hotspots** — where this project's defects actually cluster |
| `list_projects()` / `get_state(project)` | everything with a baseline / the raw state |

`project` is a key under the solo root (`~/.claude/verdict/`, override with `VERDICT_HOME`)
or a repo path in team mode, which resolves `<repo>/.qa/`.

## Command-line entry points

| Command | Does |
|---|---|
| `verdict-mcp` | the MCP server above |
| `verdict-gate` | exit-code release gate for CI — keeps "never ran" distinct from "said no" |
| `verdict-validate` | checks a state file is well-formed (`--at-rest` for a committed one) |
| `verdict-run` | runs a pass through the harness |
| `verdict-facts` / `verdict-finalize` | measure-then-judge harness halves |

## Documentation

Full documentation, the plugin itself, and the published eval results live on GitHub:

- [Repository and plugin install](https://github.com/ArtJack/verdict)
- [Published eval results](https://github.com/ArtJack/verdict/blob/main/eval/README.md#published-results) — including the runs that scored badly
- [State schema](https://github.com/ArtJack/verdict/blob/main/docs/state-schema.md)
- [Changelog](https://github.com/ArtJack/verdict/blob/main/CHANGELOG.md)

MIT licensed.
