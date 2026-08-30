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
VERDICT_STRICT=1 claude -p "/qa-review delta pass for this repository" \
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

Then gate and notify however you like:

```bash
verdict-gate myrepo --max-age-hours 24 --require-harness || notify "QA gate: $?"
```

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
  claude -p "/qa-review delta pass" --dangerously-skip-permissions \
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
ExecStart=/usr/local/bin/claude -p "/qa-review delta pass" --dangerously-skip-permissions
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
