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

Then gate and notify however you like:

```bash
verdict-gate myrepo --max-age-hours 24 || notify "QA gate: $?"
```

Exit codes: `0` pass · `1` fail · `3` blocked · `4` never ran · `5` stale.
`4` and `5` are the interesting ones for a scheduler — they mean the *run*
broke, not the code.

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

(`--min-run-number-from-log` is pseudocode — capture `run_number` before the
run and pass `--min-run-number <n+1>` after, exactly like the loop in the
README. A run that died without writing state then exits `5` instead of
re-serving yesterday's verdict.)

**GitHub self-hosted runner:** the same box can also serve the Action's `run`
mode — register it as a self-hosted runner and pass `claude-oauth-token`
instead of an API key. GitHub-hosted runners then only ever execute the
keyless gate mode.
