"""The gate's policy: which changed lines a finding sits on, what blocks a merge, the
severity cap, and a contract dispute the tester raised.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from .hygiene import is_hygiene
    from .profile import RISK_CLASSES
    from .state import is_open
    from .harness_common import _git
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene import is_hygiene
    from profile import RISK_CLASSES
    from state import is_open
    from harness_common import _git


_MINOR_OR_WORSE = ("Blocker", "Critical", "Major", "Minor")


def change_lines(repo, sha_range):
    """`(path, line) -> bool`: whether `git blame` at HEAD attributes the line to a commit
    in `sha_range` — the change under review, told from the tree. None when the range is
    unknown or names no commit, because then nothing can be told apart."""
    if not repo or not sha_range:
        return None
    listed = _git(["rev-list", str(sha_range)], repo)
    commits = set((listed or "").split())
    if not commits:
        return None
    owners: dict = {}

    def in_change(path, line) -> bool:
        key = str(path)
        if key not in owners:
            out = _git(["blame", "-w", "-M", "-C", "--line-porcelain", "HEAD", "--", key], repo)
            lines = {}
            for row in (out or "").splitlines():
                parts = row.split(" ")
                if len(parts) >= 3 and len(parts[0]) == 40 and parts[2].isdigit():
                    lines[int(parts[2])] = parts[0]
            owners[key] = lines
        try:
            return owners[key].get(int(line)) in commits
        except (TypeError, ValueError):
            return False
    return in_change


def gate_policy(state: dict, bill: dict | None, risk_class: str | None = None,
                in_change=None, judgment: dict | None = None,
                contract_rule: bool = True) -> list[str]:
    """The verdict rules a judgment cannot talk its way past → what each did, for the run.

    1. **One model.** A tester whose own transcript answers on more than one model did not
       run on the model it was launched on, and its verdict is nobody's: `blocked`, with the
       models named. On 2026-10-12 the provider's safety filter stopped two responses of a
       security gate, the CLI carried on with another model and said nothing, and only the
       eval's watcher noticed.
    2. **A proven defect the change made blocks a money or security gate.** Under
       `risk_class: money` or `security`, an open, tester-filed finding that is `proven`, a
       `REAL_DEFECT`, Minor or worse, *and* cites a line `git blame` attributes to the gate's
       range (`in_change`) makes the verdict `fail` and joins the release blockers. Measured
       on the 2026-10 money key: the tester located the right defect, proved it and returned
       `pass with risks` five times in nineteen, and three times in six on fresh positives.
       Unscoped, the rule also blocked three of eight clean changes for defects that were
       already there; scoped to the change it is what Phase 2b measures. No range, no rule:
       a defect the change made cannot be told from one it found.
        3. **A fix that fails the project's own green tests is a contract dispute, not a
       blocker.** A finding whose counterfactual broke tests that pass at HEAD
       (`fix_breaks_tests` > 0) is marked `contract_dispute`, capped at Major, taken out of
       the release blockers, and a question is parked for the maintainer: the tests are
       evidence of intent, and a documented-versus-tested disagreement is theirs to settle.
       If the judgment's `fail` rested on it alone, the verdict becomes `pass with risks`.
       Inside a money or security gate's own range the money rule keeps precedence: a defect
       the change made is judged as the change, not as the project's contract. On
       2026-10-17 django-oscar's baseline said `fail` on a Critical that 22 green tests
       assert the other way and the tracker had tuned on purpose; `profile.md` turns the rule
       off with `contract_rule: off`.
    """
    models = {str(m): int(n) for m, n in ((bill or {}).get("models") or {}).items() if m}
    if len(models) > 1:
        reason = ("the tester answered on more than one model ("
                  + ", ".join(f"{m} ×{n}" for m, n in sorted(models.items())) + ")")
        state["verdict_rule"] = {"rule": "one model", "was": state.get("verdict"),
                                 "reason": reason}
        state["verdict"] = "blocked"
        return [f"verdict blocked: {reason} — no verdict is signed by a model nobody chose"]
    notes: list[str] = []
    if contract_rule:
        notes.extend(_contract_dispute(state, in_change, judgment))
    if risk_class not in RISK_CLASSES or state.get("verdict") not in ("pass", "pass with risks"):
        return notes
    if in_change is None:
        return notes + [f"risk_class {risk_class}: no gate range, so a defect the change made "
                        "cannot be told from one it found — the judgment's verdict stands"]
    proven = []
    for f in state.get("findings") or []:
        if not (is_open(f) and not is_hygiene(f)
                and str(f.get("confidence") or "") == "proven"
                and str(f.get("failure_classification") or "") == "REAL_DEFECT"
                and str(f.get("severity") or "") in _MINOR_OR_WORSE):
            continue
        if any(isinstance(a, dict) and a.get("path") and a.get("line")
               and in_change(a["path"], a["line"]) for a in f.get("anchors") or []):
            proven.append(f)
    if not proven:
        return notes
    was = state.get("verdict")
    blockers = list(state.get("release_blockers") or [])
    named = " ".join(str(b) for b in blockers)
    for f in proven:
        fid = str(f.get("id"))
        if fid not in named:
            blockers.append(f"{fid}: {f.get('title') or ''} ({f.get('severity')}, proven, in "
                            f"the change; risk_class {risk_class}: a proven defect blocks)")
    state["release_blockers"] = blockers
    state["verdict"] = "fail"
    state["verdict_rule"] = {"rule": f"risk_class {risk_class}: a proven defect the change made "
                                     "blocks",
                             "was": was, "raised_by": [str(f.get("id")) for f in proven]}
    return notes + [f"verdict raised from '{was}' to 'fail': risk_class {risk_class}, and "
                    f"{', '.join(str(f.get('id')) for f in proven)} proven in the change"]


_SEVERITY_CAP = "Major"


def _contract_dispute(state: dict, in_change, judgment: dict | None) -> list[str]:
    """Rule 3 of `gate_policy`: the findings whose fix fails the project's own green tests."""
    capped = []
    for f in state.get("findings") or []:
        n = f.get("fix_breaks_tests")
        if not (is_open(f) and not is_hygiene(f) and isinstance(n, int)
                and not isinstance(n, bool) and n > 0):
            continue
        if in_change is not None and any(
                isinstance(a, dict) and a.get("path") and a.get("line")
                and in_change(a["path"], a["line"]) for a in f.get("anchors") or []):
            continue            # the change's own defect: the money rule judges it
        f["contract_dispute"] = True
        if str(f.get("severity") or "") in ("Blocker", "Critical"):
            f["severity_was"] = f["severity"]
            f["severity"] = _SEVERITY_CAP
        capped.append(f)
    if not capped:
        return []
    ids = [str(f.get("id")) for f in capped]
    blockers = [b for b in (state.get("release_blockers") or [])
                if not any(fid in str(b) for fid in ids)]
    state["release_blockers"] = blockers
    if judgment is not None:
        for f in capped:
            judgment.setdefault("questions", []).append({
                "question": (f"{f['fix_breaks_tests']} test(s) that pass at HEAD assert the "
                             f"behaviour {f.get('id')} calls a defect, and the fix would fail "
                             f"them. Which is the contract — the tests, or what {f.get('id')} "
                             "expects?"),
                "finding": str(f.get("id")),
                "context": (f"{f.get('id')} is filed as a contract dispute: capped at "
                            f"{_SEVERITY_CAP}, not a release blocker on its own. "
                            "Verdict does not settle a documented-versus-tested disagreement."),
                "options": ["The tests are the contract: close the finding as intended behaviour",
                            "The documented behaviour is the contract: fix the code and the tests",
                            "Neither yet: decide the contract first"]})
    was = state.get("verdict")
    still = [f for f in state.get("findings") or []
             if is_open(f) and not is_hygiene(f)
             and str(f.get("severity") or "") in ("Blocker", "Critical")]
    if was == "fail" and not blockers and not still:
        state["verdict"] = "pass with risks"
        state["verdict_rule"] = {"rule": "contract dispute", "was": was, "capped": ids}
        return [f"verdict lowered from 'fail' to 'pass with risks': {', '.join(ids)} filed as a "
                "contract dispute (the fix fails tests that pass at HEAD), and nothing else blocks"]
    return [f"contract dispute: {', '.join(ids)} capped at {_SEVERITY_CAP} and taken out of the "
            f"blockers; the verdict stands at {was!r}"]
