# Security

## What this plugin can do on your machine

Installing Verdict means letting its code run in your Claude Code sessions. The README's
[trust table](README.md#what-installs-and-when-it-runs) is measured from `hooks/hooks.json`:
six hook registrations, each a stdlib-only `python3` process, every one failing open.
The agent itself has no `Edit` tool, its `Write` is confined to the QA root by a
PreToolUse hook, and a second hook — armed when the caller is the verdict agent, or under
`VERDICT_STRICT=1` — denies the common Bash write channels. That last guard is a
deny-heuristic over a command string, not a sandbox — it has been bypassed before and will
be again (the 2026-10-02 audit measured 150 strings that got through; 0.90.3 closed the 86
that were a spelling rather than a program, and says which remain); the OS is the boundary.

The code under test is the other half. From 0.94.0 every command the harness runs from the
project goes through `src/verdict_mcp/sandbox.py`:
- the gates and the test collection;
- one-test fix verification and coverage;
- the census's mutants and a tester's repro;
- the local tier's probes.

On macOS it runs inside `sandbox-exec`:
- no network but loopback, and no DNS;
- writes only to its checkout and a private temp dir, never to the checkout's `.git`,
  `.claude` or `.mcp.json` or to the QA root;
- no reads of the owner's credential stores or other projects' QA records;
- its process group killed when it returns;
- an environment built from an allowlist, never the caller's.

Elsewhere only the environment half applies, and `facts.json` says so. `verdict-run` puts the
tester's own Bash in Claude Code's sandbox:
- no network: the allowlist is strict, because in bypass mode an unlisted host otherwise goes
  through;
- every variable that looks like a credential denied;
- writes kept to the checkout, the QA root and the repository's git directory.

Before 0.94.0 a stranger's `conftest.py` ran with whatever the caller held: the API key under
`verdict-paid`, the network, `~/.ssh`.

For a repository you do not trust, run `verdict-run --sandbox required`:
- the project's code runs only inside a box;
- a profile the repository ships cannot loosen it;
- a checkout carrying Claude Code configuration of its own is refused. Its hooks would run in
  the tester's session, outside every box.

**What the box does not close.** On macOS any process can read the start-up environment of
another process of the same user, and no sandbox rule stops it. A key the Claude CLI holds in
its environment (`ANTHROPIC_API_KEY`) is therefore readable from inside the box, which only
denies it the network. Authenticate the CLI without an environment key for an untrusted
repository. Prompt injection through a repository's `CLAUDE.md` is contained by the box, not
removed.

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
