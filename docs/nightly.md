# Nightly Verdict on your own box

The pattern that fits Verdict best: the **model runs where your subscription
lives** (your Mac, a home-lab machine, a VPS), writes the QA state; CI only
*gates* on that state with the keyless `verdict-gate` — no API billing, no
secrets in CI.

## 1. One-time: a headless subscription token

On the box that will run nightly:

```bash
claude setup-token
```

This performs the browser OAuth dance once and prints a long-lived token tied
to your Claude subscription. Export it in the service environment as
`CLAUDE_CODE_OAUTH_TOKEN`. Treat it as a credential: environment or secret
store only, never in the repo. Notes:

- Quota is shared account-wide — two boxes don't double it. A nightly delta
  run is cheap; a fresh audit is not, which is one more reason the state file
  exists.
- Subscription plans map to models (Pro → Sonnet). The eval suite is how you
  decide whether that model is good enough to sign your verdicts — run
  `python3 eval/run_eval.py --mode seeded --model sonnet` and read the score,
  don't guess.

## 2. The nightly command

```bash
cd /path/to/your/repo
VERDICT_STRICT=1 claude -p "/verdict:run" \
  --dangerously-skip-permissions
```

- `VERDICT_STRICT=1` arms both scope guards for the whole session — in a
  dedicated QA session, everything is the QA run, so the hard write-scope
  guarantee applies (see "The read-only guarantee" in the README).
- The run reads `state.json` first, so this is a delta report, not a fresh
  audit. In team mode (`.qa/` committed) the state travels with the repo; in
  solo mode it lives in `$VERDICT_HOME` on the box.

**Make the runner session-limit aware.** A subscription window exhausted by daytime work
will kill the nightly run mid-flight — the CLI prints `You've hit your session limit ·
resets <time>` and exits non-zero, and the gate then correctly refuses the stale state
(exit 5). That is the safety net working, but it costs you the night. A runner that parses
the stated reset time, sleeps until it passes, and retries **once** turns a lost night
into a late one:

```bash
OUT=$(run_pass)
if echo "$OUT" | grep -qi "session limit"; then
  # parse "resets 2:40am" → seconds to wait (clamped), then retry once
  sleep "$WAIT"; OUT=$(run_pass)
fi
```

Bound it: one retry, a hard ceiling (3h), never a loop — a runner that retries forever is
how you exhaust tomorrow's window too.

**Two more lessons from the author's first scheduled night, both worth stealing:**

- **A headless session can end its turn while the delegated agent is still running.** One
  run printed a tidy plan, said it would "relay the handoff when it reports back", exited
  `0` — and wrote no state. In `-p` mode there is no "later". Say so in the prompt: *run
  the agent to completion in this session; do not spawn it in the background; do not end
  your turn until the state file and report are written.* Then verify rather than trust:
  compare `run_number` before and after, and retry once if it did not advance. The gate
  catches this either way (exit 5) — but a caught failure is still a lost night.
  Since 0.89.0 `verdict-run` also removes the mechanism behind the worst form of it: in print
  mode the CLI waits **600 seconds** for background tasks and then terminates them, so a tester
  delegated in the background is killed mid-run and the log ends with `Background tasks still
  running after 600s; terminating`. The runner exports `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`
  (your own value wins) and bounds the run with `--timeout-s` instead. If you launch `claude -p`
  yourself, set it yourself.
- **Take a lock.** Two runs sharing one QA root is precisely the collision the state
  contract warns about, and a script can even be invoked while you are editing it (ours
  was, and executed half of itself). `mkdir` is atomic and makes a fine lock; expire it on
  age so a dead run cannot block tomorrow.

**Or skip the hand-rolled loop entirely — `verdict-run` is that loop, shipped:**

```bash
verdict-run myproject --repo ~/work/myproject --model opus --prompt-file nightly-prompt.txt
```

It records the run_number the run must beat, exports `VERDICT_STRICT=1` and
`VERDICT_MODEL` (so the model that signs the verdict is measured into
`last_run.model` instead of living in your memory), parses a session-limit
error's stated reset time and waits it out once, retries once when a session
ends its turn without writing state, and exits with the gate's code —
`--min-run-number` and `--require-harness` armed by default. Everything after
a bare `--` goes to the `claude` CLI verbatim (MCP configs, permission flags).
The sections below describe what it does, for runners you build yourself.

Two things it does that the hand-rolled loop above gets for free from the
installed plugin, because `verdict-run` launches the session **isolated**
(`--setting-sources project,local` — your user-scope plugins and settings stay
out, for a reproducible run):

- **It provisions the agent and its guards** into the repository before
  launching: `.claude/agents/verdict.md` and the hook set in
  `.claude/settings.local.json`, copied from the plugin root
  (`CLAUDE_PLUGIN_ROOT`, the checkout `verdict-run` lives in, or the newest
  version in `~/.claude/plugins/cache`). Files you already have are kept and
  named on stderr, never replaced. The PyPI wheel ships neither `agents/` nor
  `hooks/`, so a PyPI-only install with no plugin refuses up front — exit 2
  and a message — rather than spending a model run that can only come back
  `blocked`. Pass `--plugin-root` to point it somewhere, or `--no-provision`
  if you manage those files yourself.
- **It passes `--dangerously-skip-permissions`** unless you supply your own
  permission flag after `--`. Nobody is there to approve a tool call in a
  headless run, and a denied call turns the pass into a read-only review; the
  provisioned write-scope and Bash-scope hooks are the control that makes
  skipping the prompt safe — that is what they exist for.

Then gate and notify however you like:

```bash
verdict-gate myrepo --max-age-hours 24 --require-harness || notify "QA gate: $?"

# On a low-churn project, add --skip-unchanged: when HEAD equals the last
# run's sha and no quarantine has expired, verdict-run re-gates the standing
# verdict and spends no model run at all. A nightly then costs nothing on the
# days nothing changed — which is the honest answer to "but I don't change
# code every day". The comparison is exact-sha: one commit behind is a reason
# TO run.
#
# The runner streams the session transcript into your log as it happens and
# prints a heartbeat (VERDICT_HEARTBEAT_S, default 60s) when the child goes
# quiet — so a hung run is visible while it hangs, and a killed run leaves
# its partial log behind instead of nothing.

# Gating a merge rather than watching a nightly? Add --max-commits-behind 0:
# a verdict ages in commits as well as hours, and a `pass` measured before the
# commits you are about to merge is a false green. Leave it off when the run
# and the gate see different checkouts — a profile's Repo-Path records the main
# worktree, so a run inside a linked worktree legitimately reports a distance.
```

**Get the findings in front of whoever fixes things.** `verdict-issues myrepo` prints
what it would file — one issue per open finding, worst first — and `verdict-issues myrepo
--create` files them through your own `gh` login, once each, recorded in `issues.json`
beside the state so tomorrow's run adds only what is new — with one exception, because a
finding that *came back* is news: a REGRESSED finding is filed again, once per regression,
with the trail back to the issue it recurred from. It never closes an issue: a closed
issue is a person's claim, and `fix_verified` is the harness's.

Exit codes: `0` pass · `1` fail · `3` blocked · `4` never ran · `5` stale ·
`6` hand-written. `4`, `5` and `6` are the interesting ones for a scheduler —
they mean the *run* broke, not the code.

`--require-harness` is what keeps an unattended run honest. It checks four traces that only
`verdict-facts` / `verdict-finalize` leave: facts measured *for this run* (a stale
`facts.json` from an earlier one does not count), a judgment file, a computed state, and a
rendered report. Without it a run can quietly go back to composing its timestamps and
counts by hand, and nothing downstream would be able to tell — which is exactly what
happened for three releases before anyone checked.

## 3. Scheduling

**cron** (Linux or macOS):

```cron
15 3 * * * cd /path/to/repo && VERDICT_STRICT=1 CLAUDE_CODE_OAUTH_TOKEN=... \
  claude -p "/verdict:run" --dangerously-skip-permissions \
  >> ~/verdict-nightly.log 2>&1
```

**systemd timer** (Linux server — e.g. an always-on VPS):

```ini
# /etc/systemd/system/verdict-nightly.service
[Unit]
Description=Nightly Verdict QA delta run
[Service]
Type=oneshot
User=qa
WorkingDirectory=/srv/repo
Environment=VERDICT_STRICT=1
EnvironmentFile=/etc/verdict/token.env   ; holds CLAUDE_CODE_OAUTH_TOKEN=...
ExecStart=/usr/local/bin/claude -p "/verdict:run" --dangerously-skip-permissions
ExecStartPost=/usr/local/bin/verdict-gate srv-repo --min-run-number-from-log

# /etc/systemd/system/verdict-nightly.timer
[Unit]
Description=Run Verdict nightly
[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
[Install]
WantedBy=timers.target
```

Provision the hooks by **reading the plugin's `hooks/hooks.json`**, never by restating the
list in your unit file. Two hand-written copies of it — one in the eval runner, one in a
nightly script — both silently missed the PostToolUse state validator when it shipped, so
neither ever ran the guard set production runs use.

(`--min-run-number-from-log` is pseudocode — capture `run_number` before the
run and pass `--min-run-number <n+1>` after, exactly like the loop in the
README. A run that died without writing state then exits `5` instead of
re-serving yesterday's verdict.)

**The model is on probation, permanently.** Make the verdict-signing model a config file,
not a constant, and keep a small ledger of run outcomes. The author's rule: **2 non-ok
runs in the trailing 5 demote the model to the fallback** (a stronger one), with a
notification; the demoted model's ledger is wiped so a deliberate re-promotion — pass the
eval, edit the file — starts clean instead of instantly re-demoting on inherited failures.
Two definitions matter:

- **non-ok = the run failed to write state** (the model's discipline broke: it ended its
  turn early, hit a limit twice, wandered off). That is a fact about the *model*.
- **verdict `fail` is never non-ok** — that is a fact about the *code*, and it is exactly
  what the model is employed to report. A probation rule that punishes bad news teaches
  the model to stop delivering it.

This is the reward loop done honestly: the score selects *which configuration runs*, and
the agent being judged never sees its own ledger.

**GitHub self-hosted runner:** the same box can also serve the Action's `run`
mode — register it as a self-hosted runner and pass `claude-oauth-token`
instead of an API key. GitHub-hosted runners then only ever execute the
keyless gate mode.

## A night that spends no model

`verdict-run --skip-unless-drift` (0.86.0) extends `--skip-unchanged`: when HEAD moved but
the commits touched nothing any finding cites, the gates are green with parsed counts, the
test-id set is unchanged and no quarantine is due, the runner finalizes a **sweep** — the
previous verdict carried by id, `run_type: sweep`, `last_run.model: none`, the run number
advanced so the gate's freshness reads true — and spends nothing. Any condition failing is
printed as the reason, and the model runs as usual. The conditions are the harness's own
measurements (`docs/state-schema.md`, "The model-free night").

```
verdict-run myapp --skip-unless-drift --max-age-hours 26 --fail-on risks
```

## A night that spends no Claude tokens at all

The sweep answers "nothing a finding cites moved". `--on-drift` (0.90.0) answers the harder
half: something *did* move, and this is a run nobody asked for. The night steps down a tier
instead of reaching for the expensive model.

```
verdict-run myapp --on-drift local \
  --local-env-file ~/.config/verdict-gateway.env --local-model qwen3
```

`--on-drift local` and `--on-drift none` both imply `--skip-unless-drift`, and **neither can
reach the `claude` CLI at all** — that is the property, not a side effect. What happens, in
order:

| Condition, all harness-measured | What runs | State written | Exit |
|---|---|---|---|
| HEAD unchanged, no quarantine due | nothing; the standing verdict is re-gated | none | the gate's |
| HEAD moved, nothing a finding cites | the model-free sweep | run advances, `model: none` | the gate's |
| the sweep is blocked, the gateway answers | `verdict-local --delta` | `last_run.engine: verdict-local` and its counters | the gate's |
| the sweep is blocked, the gateway is down | nothing at all | none | 5, loud |
| the sweep is allowed, the gateway is down | the sweep, plus one `not_tested` line saying the model was unreachable | as above | the gate's |
| the local run got no answers | nothing is finalized; the run marker stays | none | 5, loud |
| no gate produced counts | the local delta, verdict forced `blocked` | `blocked` | 3 |
| `--on-drift none` | the sweep, or nothing | as above, or none | the gate's, or 5 |

`--on-drift local` with no `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` — in
`--local-env-file` or in the environment — is **exit 2 before anything runs**. The alternative
is the one an unattended night must never have: quietly spending the expensive model instead.

What a local night is, and what it is not: the harness measures the repository exactly as it
does for the agent — the gates, the id ledger, diff coverage, every anchor re-hashed, each open
finding's cited test re-run at both commits — and a small model answers a few dozen bounded
questions about single functions of the diff. There is no exploratory charter, no archaeology
and no adversarial reading of the suite, and the report says so in numbers. The safety rules
that make it usable over a project with a backlog:

- **A finding is never closed by silence.** Every prior open finding is resolved by a measured
  fail→pass on a test somebody *chose* (`verification_test`, or one the collector saw for the
  first time this run), carried by id, or re-filed under its own id with the drift that moved
  its evidence. The invariant is asserted before anything is finalized; a gap refuses the run.
- **The verdict is monotone.** A previous `fail` stays `fail`, and a previous `blocked` stays
  `blocked` — the second because `blocked` means an earlier run could not test at all, and this
  engine cannot tell whether what blocked it has cleared. A carried `blocked` says so in
  `not_tested`. This tier can make a verdict worse or leave it alone, never better.
- **A quarantine is released by measurement, not by its expiry date** — five identical runs of
  the one test, and the FLAKY finding stays open with the measurement added to it.
- **A returning defect is REGRESSED; an open one is not filed twice.** Before filing, a claim
  is matched to earlier findings — by a line hash the finding's anchors recorded, else by
  the function the finding names. A resolved match comes back under its own id; an open one
  is held back and counted in `not_tested`.
- **A red gate is a `fail`.** A suite with failing tests is the plainest thing a QA run can
  know, and it outranks every reading: a strong model classifies a failure and may still
  ship, this engine cannot be trusted to make that call. Measured — without this rule it
  reported `pass with risks` over three failing tests.
- **No counts, no verdict**: a run where no gate produced test counts is `blocked`.
- **A run that got no answers writes no state**, and leaves its marker, so tomorrow knows the
  night was lost.
- **Each question asks for an 8,192-token window** (`--num-ctx`, `VERDICT_LOCAL_NUM_CTX`; 0
  leaves the server's default). Ollama serves every model at 4,096 tokens unless told otherwise
  and keeps only the *end* of a longer prompt — the instructions go first. Sent on the request,
  so no server needs reconfiguring; a gateway that refuses the parameter is asked again without
  it, once, with a warning. On a GTX 1070 an 8B model at 8,192 tokens is 6.4 GB, all on the GPU.

For a PR rather than a nightly, point it at a throwaway QA root:

```
verdict-local --repo . --base main --qa-root /tmp/pr.qa \
  --reference-state ~/.claude/verdict/myapp/state.json \
  --env-file ~/.config/verdict-gateway.env
```

`--qa-root` is **required** with `--range`/`--base`: in a linked worktree `derive_key` returns
the *main* worktree's key, so without it a judgment about an unmerged branch would overwrite
the project's own record. Copy the key's `profile.md` into that directory and nothing else.
`--reference-state` reads the real state read-only, to say which of its open findings the diff
touches. The run prints a short summary ending in `Claude tokens: 0`, and `facts.needs_claude`
names what a real model run is still owed: changed lines nothing executed, open findings the
diff touches, high-severity claims no counterfactual could prove, drift nobody read, a diff
with no Python in it, parked questions, a range larger than the caps.

## Which account pays, and which endpoint answers

A scheduled run spends whatever the CLI happens to be signed into. That is rarely what
you want: a nightly should not eat the allowance you are using to work, and some teams
would rather it never left the building at all. `verdict-run --env-file <path>` merges a
`KEY=VALUE` file into the run's environment, so the choice lives in a file you own
(`chmod 600`) instead of in a command line, a crontab, or a log.

**A dedicated account.** Sign it in once, into its own configuration directory:

```bash
CLAUDE_CONFIG_DIR=~/.config/claude-verdict claude      # sign in, then /exit
```

```
# ~/.config/verdict-run.env
CLAUDE_CONFIG_DIR=/home/you/.config/claude-verdict
```

Every `verdict-run --env-file ~/.config/verdict-run.env` then spends that subscription,
and your interactive sessions are untouched.

**A gateway, or a local model server.** Anything that speaks the Anthropic messages API
— LiteLLM in front of Ollama, vLLM, a corporate proxy — works the same way:

```
# ~/.config/verdict-run.env
ANTHROPIC_BASE_URL=http://gateway:4000
ANTHROPIC_AUTH_TOKEN=sk-...
CLAUDE_CONFIG_DIR=/home/you/.config/claude-verdict-gateway
```

then `verdict-run … --model <the gateway's model name>`.

Two things about that setup are not obvious, and both cost an afternoon to find:

- **A signed-in CLI ignores `ANTHROPIC_AUTH_TOKEN`.** It sends its own stored credential,
  the gateway rejects a key nobody configured, and the error names a key you have never
  seen. The config directory must have no login in it — that is what makes the gateway
  credential the only one available.
- **A config directory the CLI has never seen refuses bypass-permissions mode, silently.**
  A headless run there exits 0 having done nothing: no output, no state, no transcript,
  which the gate reports as a lost run. `verdict-run` seeds the trust flags itself before
  launching, so this is handled; if you build your own launcher, seed them or you will
  debug a model that never ran.

The runner prints which account or endpoint it resolved, so a nightly log says what it
spent. A model served this way is not the model the eval measured — see
[eval/README.md](../eval/README.md) before trusting a verdict from one.
