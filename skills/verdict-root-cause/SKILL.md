---
name: verdict-root-cause
description: Trace a failure to its root cause with proof, not a story — a four-link chain (symptom, mechanism, origin, class), a counterfactual in an isolated scratch copy, trigger separated from cause, and a diagnosis of where the fix belongs. Use on a failing test, a bug report, or a finding whose cause is disputed.
---

# Verdict: root cause — the chain, not the label

A plausible causal story reads as true and almost nobody checks it. A cause is a claim like
any other: **evidence or `HYPOTHESIS:`**.

**In Claude Code with the Verdict plugin, use `/verdict:cause <symptom>`.** This skill is
the same procedure for agents that cannot run it.

## Procedure

1. **Reproduce first.** An unreproduced symptom has no cause worth naming — say what is
   missing and stop (`blocked`).
2. **Classify** before explaining (see `verdict-flaky-triage`): a brittle test and a real
   defect have different causes and different owners.
3. **Build the chain, one citation per link:**

   | Link | The question | What settles it |
   |---|---|---|
   | Symptom | What was observed? | The failing output, exact excerpt |
   | Mechanism | What sequence produces it? | The values and lines that carry it: `read at A:12 ← set at B:40 ← from input C` |
   | Origin | Where did it enter? | `git log -S` / `-L`, blame or bisect naming the commit |
   | Class | Instance or pattern? | A search for the same shape, with the hits — or the pattern searched and "the only site" |

   The class link is not optional: a fix aimed at the reported instances leaves the pattern
   alive. One class is one finding — list the other sites under `root_cause.class.sites`
   rather than filing them separately.
4. **Prove causation**, strongest first: **counterfactual** (flip the suspected cause in a
   scratch copy — never the checkout — and show the symptom flips with it; the scratch must
   import its own source and its own bytecode, and the control runs in the failing
   direction: original source back, symptom gone; details in `verdict-verify-fix`) ·
   **differential** (same operation succeeds here and fails there; name the one variable) ·
   **archaeology** (the symptom appears exactly at commit C, and C touches the mechanism) ·
   **reading** (the weakest: it cannot tell you what else also does it).
5. **Separate three things people call "the cause":** the **trigger** (what made it
   visible now — fixing it hides the defect), the **cause** (the code or contract that is
   wrong — what the fix targets), the **latent condition** (what let it exist and survive —
   a missing test, an unenforced invariant; left alone it produces the next instance).
6. **Depth rule:** keep asking "and why did that hold?" only while each answer has
   evidence. The first answer without evidence ends the chain, labelled `HYPOTHESIS:` with
   the one experiment that would settle it. A short true chain beats a long invented one.
7. **Stop at diagnosis.** Name where the fix belongs — code, test, spec, environment or
   process. Writing the fix is not yours.
8. **Record the chain** in the finding's `root_cause` (`mechanism`, `origin`,
   `class{pattern, sites[]}`, `trigger`, `latent_condition`, `fix_location`,
   `proof{method, evidence}`, `confidence`) so the next run inherits the diagnosis; the
   harness resolves the origin commit's date and reports how long the defect lived before
   detection.

Verdict reports and specifies; it never fixes. Route the fix to the implementer, then
verify it (`verdict-verify-fix`).
