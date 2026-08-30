---
description: "Trace a failure, bug, or finding to its root cause — with proof, not a story."
argument-hint: "<failing test, error, finding id, or symptom description>"
---

Use the `verdict` agent to find the root cause of:

`$ARGUMENTS`

Required flow (§3.5):

1. **Reproduce first.** An unreproduced symptom has no cause worth naming — say so and
   stop, or state exactly what is missing (`blocked`).
2. **Classify** per §3 before explaining: a `BRITTLE_TEST` and a `REAL_DEFECT` have
   different causes and different owners.
3. **Build the chain** — symptom → mechanism → origin → class — with a citation on every
   link. Name the proof method per link (counterfactual / differential / archaeology /
   reading), and prefer the counterfactual: flip the suspected cause in a scratch copy of
   the tree and show the symptom flips with it.
4. **Answer the class question explicitly**: search the repository for the same shape and
   report the hits, or state the pattern you searched and that this is the only site. A
   cause report without this is incomplete.
5. **Separate trigger, cause, and latent condition.** Say which is which, and what each
   one costs if left alone.
6. **Name where the fix belongs** — code, test, spec, environment, or process — and stop
   there. Do not write the fix.
7. Record the chain in the finding's `root_cause` object, update state per §6, and close
   with the §13 handoff.

If the evidence runs out mid-chain, end it there and label the remainder `HYPOTHESIS:`
with the one experiment that would settle it. A short true chain beats a long invented one.
