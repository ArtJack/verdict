# The recall benchmark — what a run misses

Every other row in `eval/` scores precision against an authored answer key. This scores recall
on defects nobody planted: findings hand-verified on strangers' repositories (a fresh clone, a
standalone script, an expected value derived by hand), fixed upstream defects gated at the
commit that introduced them (the money key), and clean changes that must not be blocked.

- `build_cases.py` turns a record's open, proven Major+ findings into known defects — anchor
  files from the record, naming words from the title — and marks the hand-verified ones.
- `score_recall.py` reads any later run's `state.json` and answers, per known defect:
  **located**, **proven** (filed `proven` with a reproduced `repro`), **blocked** (the verdict
  is `fail` and the finding blocks). It counts the run's Major+ findings that match no known
  defect (candidates for false findings, read by hand), flags a false block on a clean change,
  and prices the run from `usage.jsonl`.

The case file lives outside this repository: some known defects are undisclosed. The first
file (2026-10-17) holds the six October stranger records — 17 proven Major+ findings, 9 of
them hand-verified — and is the "before" column for every model-facing change in 0.91.0.

Protocol: a change to the prompt, the reading map or the harness rules is measured by re-running
the same cases into scratch roots and scoring both. A score is n=1 until repeated; a row that
misses is first suspected of a scorer miss (a renamed file, a title that uses other words).
