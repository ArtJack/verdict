#!/usr/bin/env python3
"""verdict-local — a QA run driven by the harness, with a small model as a subroutine.

The agent shape cannot shrink to a 7B model, and no amount of prompt tuning will make
it. Measured on this project's own runs: 38 model turns each re-reading ~53k tokens of
context, of which ~19k is fixed preamble (the 13k contract plus the measured facts)
before the investigation starts. A model with a 40k window has nothing left to think
with, and one served at 4k cannot even receive the system prompt.

So this mode inverts the control. Python does everything deterministic — measure the
gates, read coverage, list the source, slice it into functions, run a test, apply a
counterfactual in a scratch copy, validate the JSON, assemble the state — and the model
answers one bounded question at a time, with a few hundred tokens of context and a
schema it must fill. Nothing accumulates: each call is independent, so the context never
grows and a weak model is never asked to hold a plan in its head.

Measured 2026-09-08, `qwen3:8b` on a local Ollama behind a LiteLLM gateway: asked whether
each function in a module implements its own docstring, with 340 tokens of input, it
found two of the fixture's seeded defects — the `>` that should be `>=`, and `round()`
where the spec says half-up — in 30 seconds. That is the whole thesis: the judgment is
within reach of a small model; the 38-turn agent loop is not.

What is *not* claimed: this mode is not the agent. It has no exploratory charter, no
archaeology, no adversarial reading of the suite. It answers a fixed set of questions
well enough to file findings a person can act on, and it says so in the report.

Three shapes, all of them local:

    verdict-local --repo . --env-file ~/.config/gw.env            a first baseline
    verdict-local --repo . --delta --env-file ~/.config/gw.env    tonight's delta
    verdict-local --repo . --base main --qa-root /tmp/pr.qa ...   a branch, a PR

The delta is the one that took a release to get right. A cheap engine's real hazard
is not a wrong finding — a hypothesis held at Minor is cheap to check — it is the
*silence* of the findings it never mentions: `merge()` reads an unmentioned finding
as resolved, so a run that carried nothing forward closed a backlog it had never
looked at. So every prior open finding leaves a delta in one of exactly three
places: resolved by a measured fail→pass on a test somebody chose, carried by id
because its cited code is where it was, or re-filed under its own id because that
code changed and nothing here read the change. The invariant is asserted before
anything is finalized, and the verdict is monotone: this engine can make a verdict
worse or leave it alone, never better.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

try:
    from .harness import finalize_main, finding_hash, is_test_file
    from .filed import FINDINGS_DIR
    from .profile import ProfileError, gates_from
    from .profile import load as load_profile
    from .project_key import derive_key
    from .state import home as state_home
    from .state import norm_status, resolve_root, root_refusal
    from .validate import known_tests, validate_finding
    from . import clock, languages
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import languages
    from harness import finalize_main, finding_hash, is_test_file
    from filed import FINDINGS_DIR
    from profile import ProfileError, gates_from
    from profile import load as load_profile
    from project_key import derive_key
    from state import home as state_home
    from state import norm_status, resolve_root, root_refusal
    from validate import known_tests, validate_finding
# Split out of this file by the structure pass (2026-11-15), and imported back for the code
# below and for callers that import these names from small.
try:
    from .local_model import (DEFAULT_NUM_CTX, DEFAULT_TIMEOUT_S, Model, gateway_alive,
                              extract_json as extract_json)
    from .local_chunks import (Chunk as Chunk, chunks_of as chunks_of, gap_functions,
                               gap_hint as gap_hint, MAX_SOURCE_LINES as MAX_SOURCE_LINES)
    from .local_candidates import (added_lines, candidates, changed_files, changed_lines_in,
                                   changed_lines_of, chunks_in_range as chunks_in_range,
                                   delta_candidates, python_in, readable_in)
    from .local_questions import (capped_failure as capped_failure, examine as examine,
                                  finding_of as finding_of, CLASSIFY_Q as CLASSIFY_Q,
                                  CONTRACT_Q as CONTRACT_Q, capped as capped,
                                  classify_question as classify_question,
                                  contract_question as contract_question)
    from .local_probes import (counterfactual as counterfactual, PROBE_Q as PROBE_Q,
                               import_roots as import_roots, module_name as module_name,
                               probe_root as probe_root, run_probe as run_probe,
                               safe_probe as safe_probe, safe_replacement as safe_replacement,
                               scratch_copy as scratch_copy, source_root as source_root)
    from .local_skips import (group_skips, skip_finding, skip_scan_files, skips_without_expiry,
                              collected_test_files as collected_test_files,
                              has_expiry as has_expiry)
    from .local_suite import (GATE_DEFAULT, QUARANTINE_DAYS, brittle_findings, classify,
                              failure_finding, failures_of, flaky_finding, focus_finding,
                              rerun_failures, unstable, deterministic_kind as deterministic_kind,
                              words_of as words_of)
    from .local_carry import (carry_invariant, drift_note, partition_prior, refiled_finding,
                              measured_resolution as measured_resolution)
    from .local_quarantine import (REQUARANTINE_RUNS, failure_on_record, flaky_findings_by_test,
                                   merge_quarantine, released_ids, requarantine)
    from .local_verdict import (CARRIED_BLOCKED, counts_measured, gate_failed, local_verdict,
                                unexercised_diff, verdict_for as verdict_for)
    from .local_leads import (FOCUS_LINES, LEADS_FILE, LEADS_IN_FOCUS, NO_CODE_READ,
                              NO_PROBE as NO_PROBE, READ_NOT_RUN, _unique, needs_claude)
    from .local_budget import Budget, MAX_FUNCTIONS
    from .local_findings import (PriorIndex, file_findings, focus_names, regressed_finding,
                                 ordered_chunks as ordered_chunks)
    from .local_env import (ENGINE, REUSE_MAX_AGE_MIN, interpreter_of, measure,
                            plaintext_env_files, probes_off, read_json, read_reference,
                            touches_findings, _RUNNER_PYTHON as _RUNNER_PYTHON,
                            _gate_tokens as _gate_tokens)
    from .local_summary import (leads_text, not_tested_lines, print_summary, read_env_file,
                                resolve_range, written_verdict)
except ImportError:  # executed as a bare script
    from local_model import (DEFAULT_NUM_CTX, DEFAULT_TIMEOUT_S, Model, gateway_alive,
                             extract_json as extract_json)
    from local_chunks import (Chunk as Chunk, chunks_of as chunks_of, gap_functions,
                              gap_hint as gap_hint, MAX_SOURCE_LINES as MAX_SOURCE_LINES)
    from local_candidates import (added_lines, candidates, changed_files, changed_lines_in,
                                  changed_lines_of, chunks_in_range as chunks_in_range,
                                  delta_candidates, python_in, readable_in)
    from local_questions import (capped_failure as capped_failure, examine as examine,
                                 finding_of as finding_of, CLASSIFY_Q as CLASSIFY_Q,
                                 CONTRACT_Q as CONTRACT_Q, capped as capped,
                                 classify_question as classify_question,
                                 contract_question as contract_question)
    from local_probes import (counterfactual as counterfactual, PROBE_Q as PROBE_Q,
                              import_roots as import_roots, module_name as module_name,
                              probe_root as probe_root, run_probe as run_probe,
                              safe_probe as safe_probe, safe_replacement as safe_replacement,
                              scratch_copy as scratch_copy, source_root as source_root)
    from local_skips import (group_skips, skip_finding, skip_scan_files, skips_without_expiry,
                             collected_test_files as collected_test_files,
                             has_expiry as has_expiry)
    from local_suite import (GATE_DEFAULT, QUARANTINE_DAYS, brittle_findings, classify,
                             failure_finding, failures_of, flaky_finding, focus_finding,
                             rerun_failures, unstable, deterministic_kind as deterministic_kind,
                             words_of as words_of)
    from local_carry import (carry_invariant, drift_note, partition_prior, refiled_finding,
                             measured_resolution as measured_resolution)
    from local_quarantine import (REQUARANTINE_RUNS, failure_on_record, flaky_findings_by_test,
                                  merge_quarantine, released_ids, requarantine)
    from local_verdict import (CARRIED_BLOCKED, counts_measured, gate_failed, local_verdict,
                               unexercised_diff, verdict_for as verdict_for)
    from local_leads import (FOCUS_LINES, LEADS_FILE, LEADS_IN_FOCUS, NO_CODE_READ,
                             NO_PROBE as NO_PROBE, READ_NOT_RUN, _unique, needs_claude)
    from local_budget import Budget, MAX_FUNCTIONS
    from local_findings import (PriorIndex, file_findings, focus_names, regressed_finding,
                                ordered_chunks as ordered_chunks)
    from local_env import (ENGINE, REUSE_MAX_AGE_MIN, interpreter_of, measure, plaintext_env_files,
                           probes_off, read_json, read_reference, touches_findings,
                           _RUNNER_PYTHON as _RUNNER_PYTHON, _gate_tokens as _gate_tokens)
    from local_summary import (leads_text, not_tested_lines, print_summary, read_env_file,
                               resolve_range, written_verdict)
# What a gate run may spend. A PR gate that takes an hour is a gate nobody
# waits for, so the caps are the product decision: six files, twenty-four
# functions, six counterfactuals, two minutes per call and fifteen minutes of
# model time in total. Estimated on the author's GTX 1070 at roughly sixteen
# minutes for a PR-sized diff.
GATE_MAX_FILES = 6
GATE_MAX_FUNCTIONS = 24
GATE_MAX_PROBES = 6
GATE_CALL_TIMEOUT_S = 120
GATE_MODEL_BUDGET_S = 900
# A night on a project with state. Measured on Sales (2026-09-18): with no model-time budget
# a day's range of 744 unexercised changed lines kept the engine asking for 4 h 10 min — 190
# questions, 60 functions read, 259 skipped at the function cap — and a nightly that runs into
# the working day is a nightly nobody keeps. An hour, 24 functions, 12 proofs: the
# ranking puts the riskiest changed functions first, and what is left is counted, not hidden.
NIGHT_MAX_FUNCTIONS = 24
NIGHT_MAX_PROBES = 12
NIGHT_MODEL_BUDGET_S = 3600


# ── the run ───────────────────────────────────────────────────────────────────


def run(repo: Path, qa_root: Path, model: Model, limit: int, gate: str | None,
        reruns: int, prove: bool = True, delta: bool = False,
        sha_range: str | None = None, reference_state=None,
        budget: Budget | None = None, reuse_facts: bool = False) -> int:
    refusal = root_refusal(qa_root, "verdict-local", repo)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    qa_root.mkdir(parents=True, exist_ok=True)
    budget = budget or Budget()
    try:
        config, profile_notes = load_profile(qa_root)
    except ProfileError as exc:
        print(f"verdict-local: {exc}", file=sys.stderr)
        return 2
    gates = [("suite", gate)] if gate else (gates_from(config) or [("suite", GATE_DEFAULT)])
    name, command = gates[0]
    # Read whatever is there, always — never `if delta`. A caller that forgot the
    # flag over a root that already holds a record would otherwise get the 0.88.0
    # behaviour back: no prior finding mentioned, and the merge resolving the lot.
    # The flag says what the operator expected, and a mismatch is worth a line.
    previous = read_json(qa_root / "state.json")
    if delta and not previous:
        print(f"verdict-local: --delta was asked for, but {qa_root} holds no state — this "
              "run is a baseline, with nothing to carry", file=sys.stderr)
    reference = read_reference(reference_state) if reference_state else None

    # Whether a counterfactual may run at all, decided before anything is measured and
    # said in `not_tested` either way: the profile's `probes: off`, `--no-prove`,
    # `--max-probes 0`, or a gate that runs no Python interpreter (audit 2026-10-02,
    # O-S-1 (4) and O-D-11). The old code fell back to Verdict's own interpreter.
    python = interpreter_of(command, repo)
    disabled = None
    if probes_off(config, profile_notes):
        disabled = "probes disabled by profile (`probes: off` in profile.md)"
    elif not prove:
        disabled = "probes disabled by flag (`--no-prove`)"
    elif budget.probes == 0:
        disabled = "probes disabled by flag (`--max-probes 0`)"
    elif python is None:
        disabled = f"proving disabled: no Python interpreter in the gate (`{command}`)"
    prove = disabled is None

    exposed = plaintext_env_files(repo)
    if exposed:
        print(f"verdict-local: not running the gates — plaintext {', '.join(exposed)} at the "
              f"checkout root: a test run could reach live services with real keys. Remove "
              "it from the checkout under test and run again. Nothing was measured or written.",
              file=sys.stderr)
        return 5
    print(f"verdict-local: measuring {repo} · gate {name}", file=sys.stderr)
    facts = measure(repo, qa_root, gates, config, sha_range, profile_notes,
                    reuse=reuse_facts)
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    measured_range = (facts.get("last_run") or {}).get("sha_range")
    ranged = bool(measured_range)
    changed = changed_files(repo, measured_range)
    if ranged:
        cold_by_file = changed_lines_of(facts)
        # A range with nothing in it — the commit the last run measured — has nothing to
        # read. Handing it an empty list fell through to the reading map: the second Sales
        # shadow night re-ranked the whole repository's least-covered files and reported
        # its empty range as too large for the caps.
        sizes = added_lines(repo, measured_range) if any(languages.readable(p) for p in changed) else None
        ranked = delta_candidates(facts, repo, changed, sizes) if changed else []
        # Coverage names the changed lines no test ran, for Python. For every other language
        # the diff itself names the changed lines: one question per function they sit in, never
        # the whole file.
        braced = [rel for rel in ranked[:limit] if languages.language_of(rel) not in (None, "python")]
        diff_lines = changed_lines_in(repo, measured_range, braced)
        targets = [(rel, diff_lines.get(rel) if rel in braced else cold_by_file.get(rel))
                   for rel in ranked[:limit]]
    else:
        ranked = candidates(facts, repo)
        targets = [(rel, None) for rel in ranked[:limit]]
    files = [rel for rel, _ in targets]
    over_limit = len(ranked) > limit
    non_python = bool(ranged and changed and not readable_in(changed))

    print(f"verdict-local: {len(files)} file(s) to read, model {model.name}"
          + (f", proving with {python}" if prove else f", {disabled}"), file=sys.stderr)
    prefix = str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[0]
    number = int(str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[1] or 1)

    findings_dir = qa_root / FINDINGS_DIR
    findings_dir.mkdir(exist_ok=True)
    counter = [number]
    collected = known_tests(qa_root)
    prior_ids = {str(f.get("id")) for f in (previous or {}).get("findings") or []
                 if isinstance(f, dict) and f.get("id")}
    prior_by_hash = {finding_hash(f): f for f in (previous or {}).get("findings") or []
                     if isinstance(f, dict) and f.get("id")}
    on_record: list = []

    def mint(entry: dict, into: Path, into_list: list, keep_id: bool = False) -> None:
        """File a finding, or refuse it — the validator decides, never the model."""
        # One identity, one finding. The harness recognises a finding by its cited path and
        # its title, and refuses a run that files the same identity twice — a refusal that
        # costs the whole night. Anything this run already filed under the same identity is
        # the same finding: its evidence is added there, and no second file is written.
        prior = None if keep_id else prior_by_hash.get(finding_hash(entry))
        twin = next((f for f in into_list if finding_hash(f) == finding_hash(entry)), None)
        if twin is None and prior is not None:
            twin = next((f for f in into_list if str(f.get("id")) == str(prior["id"])), None)
        if twin is not None:
            twin["evidence"] = list(twin.get("evidence") or []) + [
                e for e in entry.get("evidence") or [] if e not in (twin.get("evidence") or [])]
            (into / f"{twin['id']}.json").write_text(json.dumps(twin, indent=1),
                                                     encoding="utf-8")
            print(f"verdict-local: {twin['id']} again — the same identity, folded into it",
                  file=sys.stderr)
            return
        # The same across nights: an identity the record already holds is that finding.
        # Open, it is carried by id, and filing it again puts one identity under two ids —
        # found by replaying the first Sales shadow night, whose skip markers would all have
        # come back on the second, so finalize would have refused every night after the
        # first. Accepted or withdrawn, it is a person's decision that a regular expression
        # does not overturn. Resolved, it came back: under its own id, so it is REGRESSED.
        status = norm_status((prior or {}).get("status"))
        if prior is not None and status != "resolved":
            on_record.append((str(prior["id"]), status))
            print(f"verdict-local: not filed again — {prior['id']} ({status}) is this finding "
                  "already", file=sys.stderr)
            return
        if prior is not None:
            print(f"verdict-local: {prior['id']} is back — the identity it was resolved under",
                  file=sys.stderr)
            entry = regressed_finding(prior, entry,
                                      "the same file and title it was resolved under")
            keep_id = True
        if not keep_id:
            entry["id"] = f"{prefix}-{counter[0]}"
        problems = validate_finding(entry, f"{FINDINGS_DIR}/{entry['id']}.json",
                                    prior_ids, collected)
        if problems:
            print(f"verdict-local: rejected {entry['id']}: {problems[0]}", file=sys.stderr)
            return
        (into / f"{entry['id']}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
        into_list.append(entry)
        if not keep_id:
            counter[0] += 1
        print(f"verdict-local: {entry['id']} {entry['severity']} {entry.get('failure_classification', '')} "
              f"— {entry['title'][:80]}", file=sys.stderr)

    filed = []
    today = clock.today()

    # 1. What execution says. Repetition answers flakiness; the model is never asked.
    failures = failures_of(facts)
    repeats = rerun_failures(repo, command, reruns) if failures or reruns else []
    flaky = unstable(failures, repeats)
    if failures:
        print(f"verdict-local: {len(failures)} failing test(s), {len(flaky)} unstable across "
              f"{len(repeats) + 1} run(s)", file=sys.stderr)
    fresh_quarantine = []
    for test_id in sorted(flaky):
        fresh_quarantine.append({
            "test_id": test_id,
            "first_seen": today.isoformat(),
            "fail_count": sum(1 for r in [set(f["id"] for f in failures)] + [set(x) for x in repeats]
                              if test_id in r),
            "run_count": len(repeats) + 1,
            "quarantined_until": (today + timedelta(days=QUARANTINE_DAYS)).isoformat(),
            "reason": f"failed in some of {len(repeats) + 1} identical runs and passed in "
                      "others — measured, not judged",
        })
    # A test that already has an open FLAKY finding is being carried by id below;
    # filing a second one for the same instability would put two ids on one defect.
    already_flaky = flaky_findings_by_test(previous, sorted(flaky))
    for entry in fresh_quarantine:
        if entry["test_id"] in already_flaky:
            print(f"verdict-local: {entry['test_id']} is already "
                  f"{already_flaky[entry['test_id']]}; the quarantine is re-measured and the "
                  "finding carried, not filed again", file=sys.stderr)
            continue
        mint(flaky_finding(entry, len(repeats) + 1, "@"), findings_dir, filed)
    for failure in failures:
        if failure["id"] in flaky:
            continue
        # A failing test this engine already filed is that finding, still open: carried by
        # id, not classified again. The model words its title differently from night to
        # night, so the identity rule alone would file a new duplicate every night the test
        # stays red — at about ninety seconds of the night's model budget each.
        cited = failure_on_record(previous, failure["id"])
        if cited is not None:
            status = norm_status(cited.get("status"))
            on_record.append((str(cited["id"]), status))
            print(f"verdict-local: not classified again — {failure['id']} is {cited['id']} "
                  f"({status})", file=sys.stderr)
            continue
        claim = classify(model, repo, failure)
        if claim:
            mint(failure_finding(claim, "@"), findings_dir, filed)

    # 2. Skips with no expiry — a regular expression, no model call at all.
    for skip in group_skips(skips_without_expiry(repo, skip_scan_files(repo, qa_root))):
        mint((focus_finding if skip.get("kind") == "focus" else skip_finding)(skip, "@"),
             findings_dir, filed)

    # 3. What reading says, function by function — the source, then the tests.
    already_open: list = []
    leads: list | None = [] if previous else None      # a project with a record to protect
    probe_ledger: list = []                            # every counterfactual, refusals too
    asked_functions: set = set()
    examined, proven, disproven = file_findings(model, repo, targets, mint, findings_dir,
                                                filed, python, prove, budget,
                                                prior_index=PriorIndex(previous),
                                                already_open=already_open, leads=leads,
                                                probes=probe_ledger, gaps=gap_functions(facts),
                                                asked=asked_functions, focus=focus_names(facts))
    # Beside `last_run`, not inside its `local` block: that block is copied into a
    # `usage.jsonl` row every run, and the ledger is a record, not a bill.
    facts["probes"] = probe_ledger
    suite_files = ([p for p in python_in(changed) if is_test_file(p)] if ranged
                   else skip_scan_files(repo, qa_root)[:limit])
    examined += brittle_findings(model, repo, suite_files, mint, findings_dir, filed, budget,
                                 leads=leads)

    # 4. The quarantine, re-measured rather than expired by the calendar.
    carried_quarantine, released, quarantine_notes = requarantine(
        repo, (previous or {}).get("flaky_quarantine") or [], config.get("test_one_cmd"), today)
    quarantine_out = merge_quarantine(carried_quarantine, fresh_quarantine)

    # 5. Every prior open finding is mentioned — A, B or C, and nothing else.
    prior_open = [str(f.get("id")) for f in (previous or {}).get("findings") or []
                  if isinstance(f, dict) and f.get("id") and norm_status(f.get("status")) == "open"
                  and f.get("source") != "hygiene"]
    resolved_ids, still_open_ids, to_refile = partition_prior(previous, facts)
    by_id = {str(f.get("id")): f for f in (previous or {}).get("findings") or []
             if isinstance(f, dict) and f.get("id")}
    for fid in released_ids(previous, released):
        # A released quarantine changes what its FLAKY finding says about itself,
        # so the finding is re-filed with the measurement rather than carried by
        # words that are no longer true.
        if fid in still_open_ids:
            still_open_ids.remove(fid)
            to_refile.append((by_id[fid], "released", []))

    asked_questions, refiled = [], []
    for prior, drift, moved in to_refile:
        fid = str(prior.get("id"))
        note = (f"quarantine released {today.isoformat()}: the test passed "
                f"{REQUARANTINE_RUNS} of {REQUARANTINE_RUNS} identical runs and blocks "
                "releases again. The finding stays open — nothing explained why it was ever "
                "unstable" if drift == "released" else drift_note(drift, moved))
        before = len(filed)
        mint(refiled_finding(prior, note, collected), findings_dir, filed, keep_id=True)
        if len(filed) > before:
            refiled.append(filed[-1])
            asked_questions.append({
                "question": f"{fid} was re-filed unread by {ENGINE}: {note[:150]}. Is it still "
                            "real over the new code?",
                "finding": fid,
                "context": "no model read the changed code this run; the severity above is "
                           "the one the finding was filed with"})
        else:
            # Refused by the validator. Silence resolves it, so it goes back into
            # the carried set — the conservative direction, always.
            still_open_ids.append(fid)

    missing = carry_invariant(prior_open, resolved_ids, still_open_ids,
                              {str(f.get("id")) for f in filed})
    if missing:
        print(f"verdict-local: refusing to finalize — {len(missing)} prior open finding(s) "
              f"would go unmentioned ({', '.join(missing[:5])}), and the merge reads silence "
              "as resolution. No state was written; the run marker is left in place.",
              file=sys.stderr)
        return 1

    if (model.answered + model.unanswered) and not model.answered:
        print(f"verdict-local: refusing to finalize — {model.unanswered} question(s) were "
              f"asked and none was answered ({model.errors} transport error(s)). A judgment "
              "assembled from no answers is a run that measured the suite and called it QA. "
              "No judgment, no state; the run marker is left in place.", file=sys.stderr)
        return 5

    measured = counts_measured(facts)
    cold_lines = unexercised_diff(facts)
    carried_records = [by_id[f] for f in still_open_ids if f in by_id]
    # A prior state with no verdict in it is unknown, not clean — and `None` here
    # means "baseline", which would hand this run the freedom a baseline has.
    prior_verdict = (previous.get("verdict") or "blocked") if previous else None
    braced_read = examined > 0 and any(languages.language_of(rel) not in (None, "python")
                                       for rel in files)
    verdict = local_verdict(prior_verdict, filed, carried_records, measured, cold_lines,
                            ceiling=(NO_CODE_READ if non_python
                                     else READ_NOT_RUN if braced_read else None),
                            gates_failed=gate_failed(facts))

    touched = touches_findings(reference, changed) if reference else []
    owed = needs_claude(facts, filed, refiled, touched, len(asked_questions),
                        over_limit and ranged, non_python)

    blockers = _unique([b for b in (previous or {}).get("release_blockers") or []
                        if not any(str(b).startswith(fid) for fid in resolved_ids)]
                       + [f["id"] for f in filed if f.get("severity") == "Blocker"])
    # Deduplicated, and this run's lines first: a nightly that appends its own
    # focus to the previous run's forever ends up with a list nobody reads, which
    # is the same as having none.
    focus = _unique(
        [f"{f['id']}: read the changed code under this finding — {ENGINE} re-filed it "
         "without reading it" for f in refiled]
        + [f"needs a model run — {key}: {value}" for key, value in sorted(owed.items())]
        + [f"lead, unproven: {x['path']}:{x['line']} `{x['function']}` — {x['title'][:120]}"
           for x in (leads or [])[:LEADS_IN_FOCUS]]
        + [str(x) for x in (previous or {}).get("next_run_focus") or []])[:FOCUS_LINES]

    for note in quarantine_notes:
        print(f"verdict-local: {note}", file=sys.stderr)
        if "NOT re-measured" in note:
            asked_questions.append({
                "question": f"A quarantine is due and could not be re-measured: {note[:170]}",
                "context": "declare `test_one_cmd` in the profile so the harness can run one "
                           "test, or release the quarantine deliberately"})

    unread = [(path, name) for path, names in gap_functions(facts).items() for name in names
              if (path, name) not in asked_functions]
    not_tested = not_tested_lines(model, files, examined, prior_open, still_open_ids,
                                  refiled, prove, budget, quarantine_notes, non_python,
                                  disabled=disabled, unread_survivors=unread)
    if braced_read:
        not_tested.append(READ_NOT_RUN)
    if ranged and (kinds := languages.unread_summary(changed)):
        # Named by kind, so a range that changed styles and copy beside its code says what of it
        # no question looked at: a stylesheet is not program source, and nothing here reads one.
        not_tested.append(f"changed in the range and read by no question here, because none of "
                          f"it is program source: {kinds}")
    if leads:
        not_tested.append(
            f"{len(leads)} reading(s) this engine could not prove were listed as leads in the "
            "report, not filed — a lead is a question for a run that can judge it, not a finding")
    if already_open:
        # Said, not swallowed: a claim that was not filed is still something this run read.
        ids = ", ".join(sorted({fid for fid, _name, _how in already_open}))
        not_tested.append(
            f"{len(already_open)} claim(s) about function(s) that already carry an open finding "
            f"({ids}) were not filed again — whether each is that finding or a second defect "
            "in the same function was not settled")
    if on_record:
        ids = ", ".join(sorted({f"{fid} ({status})" for fid, status in on_record}))
        not_tested.append(
            f"{len(on_record)} finding(s) this run found again are already on the record "
            f"({ids}) and were not filed again — the same identity, or a failing test this "
            "engine already filed; each stays as the record has it")
    carried_blocked = prior_verdict == "blocked" and verdict == "blocked"
    if carried_blocked:
        not_tested.append(CARRIED_BLOCKED)

    judgment = {
        "topic": "local-delta" if previous else "local",
        "verdict": verdict,
        "findings": [], "still_open": still_open_ids, "resolved": resolved_ids,
        "questions": asked_questions,
        "not_tested": not_tested,
        "prose": {
            "scope": (f"{ENGINE}: {examined} function(s) in {len(files)} file(s) read one at a "
                      f"time by {model.name}, each in isolation"
                      + (f", over the range `{measured_range}`" if ranged else "")
                      + ". The harness measured the repository; the model answered bounded "
                        "questions about single functions."),
            "risks": ("Every finding read here is a `hypothesis` unless a counterfactual "
                      "proved it. This mode cannot see a defect that spans two functions, and "
                      "it reads the suite only where the range touched it."
                      + (" " + NO_CODE_READ if non_python else "")
                      + (" " + READ_NOT_RUN if braced_read else "")),
            "notes": ("No Claude tokens were spent on this run. The verdict cannot improve on "
                      "its own: a previous `fail` stays `fail`, and a previous `blocked` "
                      "stays `blocked`, until something with judgment looks at it."
                      + (" " + CARRIED_BLOCKED[0].upper() + CARRIED_BLOCKED[1:] + "."
                         if carried_blocked else "")
                      + leads_text(leads)),
        },
        "isolation_check": {"result": "pass",
                            "method": ("measured before the gates: no plaintext .env file at "
                                       "the checkout root. The profile's own isolation steps "
                                       "were not executed: this engine runs the profile's gates "
                                       "and reads code, and writes nothing outside the QA root")},
        "verified_intact": list((previous or {}).get("verified_intact") or []),
        "flaky_quarantine": quarantine_out,
        "release_blockers": blockers,
        "next_run_focus": focus,
        "full_sweep": False,
    }
    (qa_root / "judgment.json").write_text(json.dumps(judgment, indent=1), encoding="utf-8")

    # No gateway in it: this block becomes the state's `last_run.local`, which a team
    # commits. The address goes to finalize below, and from there to the bill only.
    facts["last_run"]["local"] = {
        "model": model.name,
        "calls": model.calls, "tokens": model.input_tokens + model.output_tokens,
        "input_tokens": model.input_tokens, "output_tokens": model.output_tokens,
        "answered": model.answered, "unanswered": model.unanswered,
        "retries": model.retries, "errors": model.errors, "num_ctx": model.num_ctx,
        "functions_read": examined, "functions_skipped": budget.skipped,
        "seconds": round(budget.elapsed_s(), 1),
    }
    if owed:
        facts["needs_claude"] = owed
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    # The report's leads as data, for the run that judges them next: `verdict-run --escalate`
    # hands them to the tester with the census survivors and this engine's own filings.
    (qa_root / LEADS_FILE).write_text(json.dumps({"engine": ENGINE, "model": model.name,
                                                  "leads": leads or []}, indent=1),
                                      encoding="utf-8")

    code = finalize_main(["--qa-root", str(qa_root),
                          "--judgment", str(qa_root / "judgment.json")],
                         gateway=model.base_url)
    if proven or disproven:
        print(f"verdict-local: {proven} claim(s) proven by counterfactual, {disproven} "
              f"withdrawn before filing", file=sys.stderr)
    print_summary(model, files, examined, filed, refiled, resolved_ids, still_open_ids,
                  written_verdict(qa_root, verdict) if code == 0 else verdict, owed, budget,
                  engine_verdict=verdict)
    return code


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="verdict-local", description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", default=None)
    ap.add_argument("--repo", default=None)
    # `chat`, not the alias the first nights used: DECISIONS.md 2026-09-25 measured that one
    # thinking through its whole budget and answering 1 question in 9, so a run that omitted
    # `--model` spent the night to exit 5 (audit 2026-10-02, O-D-5).
    ap.add_argument("--model", default=os.environ.get("VERDICT_LOCAL_MODEL", "chat"),
                    help="the model name sent to the gateway (default: $VERDICT_LOCAL_MODEL, "
                         "else `chat`). An alias that thinks through its whole budget "
                         "answers nothing, and the run exits 5 after the suite has run")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="KEY=VALUE file with ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN")
    ap.add_argument("--limit", type=int, default=8, metavar="N",
                    help="read at most N files, least covered first (default 8)")
    ap.add_argument("--gate", default=None, metavar="CMD",
                    help="the suite command; `{report}` is rendered to a JUnit path. "
                         "Default: the profile's gate, else pytest")
    ap.add_argument("--no-prove", dest="prove", action="store_false",
                    help="do not flip claimed lines in a scratch copy to test them; every "
                         "finding then stays a hypothesis")
    ap.add_argument("--reruns", type=int, default=2, metavar="N",
                    help="run the suite N more times to find tests that are not stable "
                         "(default 2); flakiness is measured, never asked of the model")
    ap.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--num-ctx", type=int, metavar="TOKENS",
                    default=int(os.environ.get("VERDICT_LOCAL_NUM_CTX") or DEFAULT_NUM_CTX),
                    help="the context window each question asks the server for (default "
                         f"{DEFAULT_NUM_CTX}); 0 leaves the server's own default, which on "
                         "Ollama is 4,096 and cuts long questions from the front")
    ap.add_argument("--delta", action="store_true",
                    help="a delta against the stored baseline: every prior open finding is "
                         "resolved by measurement, carried by id, or re-filed with the drift "
                         "that moved it — never left silent. Implied by a QA root that "
                         "already holds a state")
    ap.add_argument("--qa-root", default=None, metavar="DIR",
                    help="the QA root to write. REQUIRED with --range/--base: a linked "
                         "worktree resolves the MAIN worktree's project key, so a branch run "
                         "without this would write the project's own state")
    ap.add_argument("--range", dest="sha_range", default=None, metavar="BASE..HEAD",
                    help="judge this commit range instead of the one since the last run")
    ap.add_argument("--base", default=None, metavar="REF",
                    help="judge the range since the merge base with REF")
    ap.add_argument("--reuse-facts", action="store_true",
                    help="use facts.json when it was measured for this same HEAD within "
                         f"{REUSE_MAX_AGE_MIN:.0f} minutes (verdict-run's sweep attempt) "
                         "instead of running the gates again")
    ap.add_argument("--reference-state", type=Path, default=None, metavar="PATH",
                    help="the project's real state.json, read-only, to say which of its open "
                         "findings this range touches")
    ap.add_argument("--max-functions", type=int, default=None, metavar="N",
                    help=f"ask about at most N functions (default {MAX_FUNCTIONS}; "
                         f"{GATE_MAX_FUNCTIONS} when a range is named)")
    ap.add_argument("--max-probes", type=int, default=None, metavar="N",
                    help="apply at most N counterfactuals; the rest stay hypotheses")
    ap.add_argument("--max-model-s", type=int, default=None, metavar="S",
                    help="stop asking after S seconds and report what went unread")
    args = ap.parse_args(argv)

    env = dict(os.environ)
    if args.env_file:
        if not args.env_file.is_file():
            print(f"verdict-local: --env-file {args.env_file} does not exist", file=sys.stderr)
            return 2
        env.update(read_env_file(args.env_file))
    base_url, token = env.get("ANTHROPIC_BASE_URL"), env.get("ANTHROPIC_AUTH_TOKEN")
    if not base_url or not token:
        print("verdict-local: ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are required — "
              "point them at a gateway that speaks the Anthropic messages API "
              "(LiteLLM in front of Ollama, for example)", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve() if args.repo else Path.cwd()
    if (args.sha_range or args.base) and not args.qa_root:
        # P-31, and the reason this is required rather than defaulted: in a linked
        # worktree `derive_key` returns the MAIN worktree's key, so a branch run
        # would resolve — and overwrite — the project's own state root with a
        # judgment about a branch nobody has merged.
        print("verdict-local: --range/--base needs --qa-root. A branch run resolves the MAIN "
              "worktree's project key, so without it this would write the project's own "
              "state from a branch. Point it at a throwaway directory holding a copy of the "
              "key's profile.md.", file=sys.stderr)
        return 2
    sha_range = resolve_range(repo, args.sha_range, args.base)
    if args.base and not sha_range:
        return 2
    if args.qa_root:
        qa_root = Path(args.qa_root).expanduser().resolve()
        project = args.project or str(qa_root)
    else:
        project = args.project or (str(repo) if resolve_root(str(repo)) else derive_key(repo)[0])
        qa_root = resolve_root(project) or (state_home() / project)

    ranged = bool(sha_range)
    model = Model(args.model, base_url, token,
                  GATE_CALL_TIMEOUT_S if ranged and args.timeout_s == DEFAULT_TIMEOUT_S
                  else args.timeout_s, num_ctx=args.num_ctx)
    alive, detail = gateway_alive(base_url, token)
    if not alive:
        # Asked before the suite, not after. A dead gateway found at the first
        # question has already cost a whole suite run and left a marker claiming a
        # run in progress; found here, nothing is written at all and the night is
        # recorded as one where no model was available.
        print(f"verdict-local: the gateway is not answering — {detail}. Nothing was measured "
              "and no state was written: a run with no model is not a QA pass.",
              file=sys.stderr)
        return 5
    os.environ["VERDICT_MODEL"] = f"local:{model.name}"
    # Three shapes, three budgets: a gate over a range, a night over a project that already
    # has a record, and a first pass over a fresh one (unbounded in time, as before).
    night = not ranged and (qa_root / "state.json").is_file()
    budget = Budget(
        functions=(args.max_functions if args.max_functions is not None
                   else GATE_MAX_FUNCTIONS if ranged
                   else NIGHT_MAX_FUNCTIONS if night else MAX_FUNCTIONS),
        probes=(args.max_probes if args.max_probes is not None
                else GATE_MAX_PROBES if ranged
                else NIGHT_MAX_PROBES if night else None),
        seconds=(args.max_model_s if args.max_model_s is not None
                 else GATE_MODEL_BUDGET_S if ranged
                 else NIGHT_MODEL_BUDGET_S if night else None))
    # A named range is a gate somebody is waiting for, so it takes the caps
    # unless the operator overrode them: six files, and no repeat runs of the
    # whole suite — three green suites prove nothing about a diff.
    limit = GATE_MAX_FILES if ranged and args.limit == 8 else args.limit
    reruns = 0 if ranged and args.reruns == 2 else args.reruns
    print(f"verdict-local: {clock.now():%Y-%m-%dT%H:%M:%SZ} · project {project!r} · {detail}",
          file=sys.stderr)
    return run(repo, qa_root, model, limit, args.gate, reruns, args.prove,
               delta=args.delta or (qa_root / "state.json").is_file(),
               sha_range=sha_range, reference_state=args.reference_state, budget=budget,
               reuse_facts=args.reuse_facts)


if __name__ == "__main__":
    sys.exit(main())
