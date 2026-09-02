"""The run history signs itself, so `--require-harness` resists imitation.

Verdict, auditing itself, showed that exit 6 was defeated by *imitation* rather
than forgery: adding `"calibration": {}` and pasting the report footer flipped a
hand-written state from exit 6 to exit 0. Both durable signals were satisfiable
by copying what already sits in the committed `.qa/` artifacts a fabricating
model reads before it writes.

The difference a chain makes is that its value depends on the row it signs. A
link copied forward from the previous run does not verify against the new one.
That is the property these tests hold; they do not claim fabrication is
impossible, only that the cheap version of it now fails loudly.
"""

import json
import subprocess
import sys
from pathlib import Path

from verdict_mcp.harness import collect
from verdict_mcp.state import (chain_link, harness_signals, load_chain_anchor,
                               load_runs,
                               missing_durable,
                               verify_chain)

from conftest import judgment

HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"
GATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "gate.py"


def finalize(qa_root, repo, tmp_path, **judgment_overrides):
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    j = {**judgment(), **judgment_overrides}
    jp = tmp_path / "j.json"
    jp.write_text(json.dumps(j), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HARNESS), "finalize",
                           "--qa-root", str(qa_root), "--judgment", str(jp)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads((qa_root / "state.json").read_text(encoding="utf-8"))


def rows(qa_root):
    text = (qa_root / "runs.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def write_rows(qa_root, rs):
    (qa_root / "runs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rs), encoding="utf-8")


# ── what a real run produces ──────────────────────────────────────────────

def unchain(qa_root, *, drop_anchor=True):
    """Make a project look like one from before the chain existed.

    Stripping the links while LEAVING the ledger's anchor is not that — it is
    the tampering the anchor exists to catch (VERDICT-F-21) — so a test that
    wants a genuine pre-upgrade project has to drop the anchor too, exactly as
    a project that never ran a chaining finalize would not have one.
    """
    write_rows(qa_root, [{k: v for k, v in r.items() if k != "chain"}
                         for r in rows(qa_root)])
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    state["last_run"].pop("chain", None)
    (qa_root / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    if drop_anchor:
        led = json.loads((qa_root / "outcomes.json").read_text(encoding="utf-8"))
        led.pop("chain", None)
        (qa_root / "outcomes.json").write_text(json.dumps(led, indent=2), encoding="utf-8")
    return state


def test_finalize_signs_the_run_and_the_state_agrees(repo, qa_root, tmp_path):
    state = finalize(qa_root, repo, tmp_path)
    history = rows(qa_root)
    assert history[-1].get("chain"), "the run history is unsigned"
    assert state["last_run"]["chain"] == history[-1]["chain"], \
        "the state must name the link its own run wrote"
    assert verify_chain(history)["status"] == "intact"
    assert harness_signals(state, qa_root)["chain_intact"] is True
    assert missing_durable(harness_signals(state, qa_root)) == []


# ── the attacks ───────────────────────────────────────────────────────────

def test_editing_a_signed_row_breaks_the_chain(repo, qa_root, tmp_path):
    state = finalize(qa_root, repo, tmp_path)
    history = rows(qa_root)
    history[-1]["verdict"] = "pass"          # launder the verdict, keep the link
    write_rows(qa_root, history)
    assert verify_chain(rows(qa_root))["status"] == "broken"
    assert harness_signals(state, qa_root)["chain_intact"] is False


def test_a_copied_link_does_not_verify(repo, qa_root, tmp_path):
    """The F-12 case exactly: imitation, not forgery.

    A constant footer copies forward and still passes. A link cannot, because
    it is a function of the row beneath it.
    """
    finalize(qa_root, repo, tmp_path)
    signed = rows(qa_root)[-1]
    fabricated = {**signed, "run_number": signed["run_number"] + 1,
                  "verdict": "pass", "chain": signed["chain"]}
    write_rows(qa_root, [signed, fabricated])
    assert verify_chain(rows(qa_root))["status"] == "broken"


def test_dropping_the_link_is_a_break_not_a_downgrade(repo, qa_root, tmp_path):
    """Without this ratchet, a fabricator omits what it cannot compute."""
    finalize(qa_root, repo, tmp_path)
    signed = rows(qa_root)[-1]
    unsigned = {k: v for k, v in signed.items() if k != "chain"}
    unsigned["run_number"] = signed["run_number"] + 1
    write_rows(qa_root, [signed, unsigned])
    assert verify_chain(rows(qa_root))["status"] == "broken"


def test_laundering_the_state_in_place_breaks_the_link(repo, qa_root, tmp_path):
    """Verdict's F-12 attack, verbatim, against the chained project.

    The link signs the history row, and editing only `state.json` leaves that
    row untouched — which is how a laundered verdict survived the first version
    of this check. The row is derived from the state, so re-deriving it catches
    the edit.
    """
    state = finalize(qa_root, repo, tmp_path)
    state["verdict"] = "pass"
    state["release_blockers"] = []
    state["findings"] = []
    state["calibration"] = {}                    # the old signal, imitated
    (qa_root / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    assert verify_chain(rows(qa_root))["status"] == "intact", \
        "the history itself is untouched — that is the point"
    assert harness_signals(state, qa_root)["chain_intact"] is False

    proc = subprocess.run(
        [sys.executable, str(GATE), str(qa_root), "--require-harness"],
        capture_output=True, text=True)
    assert proc.returncode == 6, proc.stdout + proc.stderr


def test_a_state_may_not_claim_a_link_the_history_lacks(repo, qa_root, tmp_path):
    state = finalize(qa_root, repo, tmp_path)
    history = rows(qa_root)
    write_rows(qa_root, [{k: v for k, v in r.items() if k != "chain"} for r in history])
    assert harness_signals(state, qa_root)["chain_intact"] is False


def test_state_must_describe_the_run_the_history_ends_on(repo, qa_root, tmp_path):
    state = finalize(qa_root, repo, tmp_path)
    state["run_number"] = (state["run_number"] or 1) + 5
    assert harness_signals(state, qa_root)["chain_intact"] is False


# ── backward compatibility ────────────────────────────────────────────────

def test_a_project_from_before_the_chain_still_passes(repo, qa_root, tmp_path):
    """Existing installations must not start failing their own gate."""
    finalize(qa_root, repo, tmp_path)
    state = unchain(qa_root)
    signals = harness_signals(state, qa_root)
    assert verify_chain(rows(qa_root), load_chain_anchor(qa_root))["status"] == "unchained"
    assert signals["chain_intact"] is True
    assert missing_durable(signals) == []


def test_no_history_file_at_all_is_not_a_failure(repo, qa_root, tmp_path):
    """A project that never chained anything. Its ledger records no anchor, so
    there is nothing to say the history ever existed."""
    state = finalize(qa_root, repo, tmp_path)
    unchain(qa_root)
    (qa_root / "runs.jsonl").unlink()
    state["last_run"].pop("chain", None)
    assert harness_signals(state, qa_root)["chain_intact"] is True


def test_deleting_the_history_of_a_chained_project_is_a_break(repo, qa_root, tmp_path):
    """VERDICT-F-21: the ratchet held only inside `runs.jsonl`, so deleting the
    file and the state's own link returned the project to `unchained` — the one
    status that is accepted — and the whole signal came off with one `rm`. The
    outcome ledger, a different file with a different job, records that this
    project has been chained."""
    state = finalize(qa_root, repo, tmp_path)
    (qa_root / "runs.jsonl").unlink()
    state["last_run"].pop("chain", None)
    assert harness_signals(state, qa_root)["chain_intact"] is False
    result = verify_chain([], load_chain_anchor(qa_root))
    assert result["status"] == "broken"
    assert "carries no link at all" in result["reason"]


def test_stripping_every_link_but_keeping_the_ledger_is_a_break(repo, qa_root, tmp_path):
    """The other half of the same evasion: rewrite the history as unsigned
    rather than deleting it."""
    finalize(qa_root, repo, tmp_path)
    state = unchain(qa_root, drop_anchor=False)
    assert harness_signals(state, qa_root)["chain_intact"] is False


def test_a_rewritten_history_that_chains_perfectly_is_still_a_break(
        repo, qa_root, tmp_path):
    """The forger's best move: not an unsigned history, but a *correctly signed*
    one begun from a start of their own choosing. It verifies against itself —
    that is what internal-only ratchets can never catch — and the ledger's
    record of the run that actually happened is missing from it."""
    finalize(qa_root, repo, tmp_path)
    anchor = load_chain_anchor(qa_root)
    assert anchor.get("last_link")

    forged = {"run_number": 1, "verdict": "pass", "project": "widget"}
    forged["chain"] = chain_link("", forged)
    assert verify_chain([forged])["status"] == "intact", "the forgery is self-consistent"

    result = verify_chain([forged], anchor)
    assert result["status"] == "broken", result
    assert "truncated or rewritten" in result["reason"]


# ── the gate ──────────────────────────────────────────────────────────────

def test_gate_refuses_a_broken_chain_under_require_harness(repo, qa_root, tmp_path):
    finalize(qa_root, repo, tmp_path)
    history = rows(qa_root)
    history[-1]["verdict"] = "pass"
    write_rows(qa_root, history)
    proc = subprocess.run(
        [sys.executable, str(GATE), str(qa_root), "--require-harness"],
        capture_output=True, text=True)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "chain_intact" in proc.stdout


def test_gate_accepts_a_signed_run(repo, qa_root, tmp_path):
    finalize(qa_root, repo, tmp_path)
    proc = subprocess.run(
        [sys.executable, str(GATE), str(qa_root), "--require-harness"],
        capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    assert "chain_intact" not in proc.stdout


def test_an_unsigned_history_is_said_out_loud(repo, qa_root, tmp_path):
    """Failing every pre-upgrade project would be a migration by ambush; saying
    nothing would make an unprotected project look like a protected one."""
    finalize(qa_root, repo, tmp_path)
    unchain(qa_root)

    proc = subprocess.run(
        [sys.executable, str(GATE), str(qa_root), "--require-harness"],
        capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    assert "unsigned" in proc.stdout


def test_a_signed_history_says_nothing(repo, qa_root, tmp_path):
    finalize(qa_root, repo, tmp_path)
    proc = subprocess.run(
        [sys.executable, str(GATE), str(qa_root), "--require-harness"],
        capture_output=True, text=True)
    assert "unsigned" not in proc.stdout


def test_a_correction_is_signed_and_the_signal_still_holds(repo, qa_root, tmp_path):
    """The false alarm the revision stamp must not cause. The binding check
    re-derives the history row from the state, and the state does not know its
    own correction generation — that is stamped at write time from the ledger.
    Read it back off the signed row, or every legitimate correction reports as
    tampering and the operator learns to ignore the one signal that matters."""
    finalize(qa_root, repo, tmp_path, run_label="first finalize, miscounted")
    (qa_root / "state.json").unlink()  # the operator's rollback
    state = finalize(qa_root, repo, tmp_path, run_label="corrected")
    raw = [json.loads(line) for line in
           (qa_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert raw[-1]["revision"] == 1, "the correction is stamped on the row"
    assert harness_signals(state, qa_root)["chain_intact"] is True


def test_bumping_a_stored_revision_breaks_the_chain(repo, qa_root, tmp_path):
    """`load_runs` awards a duplicated run number to the highest revision, so
    an edited revision would be a way to resurrect a superseded verdict — if
    the field were not inside the signed body. It is, so the resurrection dies
    at the chain walk, before any reader ever compares generations."""
    finalize(qa_root, repo, tmp_path)
    path = qa_root / "runs.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").strip())
    row["revision"] = 7
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    rows, _ = load_runs(qa_root)
    assert verify_chain(rows)["status"] == "broken"


def test_the_chain_extends_over_a_correction_not_around_it(repo, qa_root, tmp_path):
    """Run 2 links to the correction that won run 1, and the walk verifies over
    the winners. The superseded row stays on disk — append-only is the point —
    but it is no longer part of the story the chain tells."""
    finalize(qa_root, repo, tmp_path, run_label="first")
    (qa_root / "state.json").unlink()
    finalize(qa_root, repo, tmp_path, run_label="corrected")
    state = finalize(qa_root, repo, tmp_path)  # run 2, nothing unusual about it
    raw_lines = (qa_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 3, "the stale row is never removed"
    rows, _ = load_runs(qa_root)
    assert [r["run_number"] for r in rows] == [1, 2]
    assert verify_chain(rows)["status"] == "intact"
    assert harness_signals(state, qa_root)["chain_intact"] is True
