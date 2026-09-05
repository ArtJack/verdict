# Security

## What this plugin can do on your machine

Installing Verdict means letting its code run in your Claude Code sessions. The README's
[trust table](README.md#what-installs-and-when-it-runs) is measured from `hooks/hooks.json`:
six hook registrations, each a stdlib-only `python3` process, every one failing open.
The agent itself has no `Edit` tool, its `Write` is confined to the QA root by a
PreToolUse hook, and under `VERDICT_STRICT=1` a second hook denies the obvious Bash
write channels. That last guard is a deny-heuristic over a command string, not a
sandbox — it has been bypassed before and will be again; the OS is the boundary.

Nothing routes through the author. No telemetry, no network calls from the plugin; the
optional MCP server is read-only over local files; the GitHub Action's run mode uses your
key in your repository.

## Reporting a vulnerability

A way past the scope guards, a state the validator admits that it should refuse, a path
by which the tester could edit code or launder a verdict — report it privately first:

- **Email:** hello@artjeck.com with `[verdict security]` in the subject.
- Or open a [GitHub security advisory](https://github.com/ArtJack/verdict/security/advisories/new).

Include the command or state that demonstrates it, the way a finding would. Guard
bypasses are fixed as a class, not an instance (the 2026-08 external audit named six;
re-probing the same classes found eighteen more), and every fix ships with the bypass
pinned as a regression test. Expect an acknowledgement within a few days and a fix in a
tagged release; credit is given in the CHANGELOG unless you prefer otherwise.

Findings that are not security-sensitive — a wrong classification, a rendering defect, a
scorer error — go in a normal issue.

## Supported versions

The latest tagged release. The plugin updates in place
(`claude plugin update verdict@verdict`); the PyPI distribution `verdict-qa-mcp` tracks the
same version line.
