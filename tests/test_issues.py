"""verdict-issues: open findings → GitHub issues, once, and nothing without --create.

`gh` is stood in for by a stub that records what it was asked and hands back a
numbered URL — what these tests guard is the ledger, the dedupe and the
dry-run wall, not GitHub.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ISSUES = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "issues.py"


def make_home(tmp_path, findings):
    home = tmp_path / "home"
    root = home / "widget"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# r", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "schema_version": 1, "run_type": "delta", "run_number": 7,
        "last_run": {"timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "git_sha": "abc", "report": "reports/r.md"},
        "isolation_check": {"result": "pass"}, "gates": {}, "tests": {}, "flaky_quarantine": [],
        "verdict": "fail", "release_blockers": [], "not_tested": ["x"], "findings": findings,
    }), encoding="utf-8")
    return home


def finding(fid, sev, status="open", title=None):
    return {"id": fid, "hash": fid.lower(), "status": status, "severity": sev, "priority": "P1",
            "title": title or f"{fid} is broken", "first_seen": "2026-08-30", "age_days": 3,
            "failure_classification": "REAL_DEFECT", "confidence": "proven",
            "evidence": [f"{fid.lower()}.py:1 the defect", "tests/test_x.py::test_y fails"]}


STUB_GH = '''
import json, os, sys
from pathlib import Path
argv = sys.argv[1:]
body = Path(argv[argv.index("--body-file") + 1]).read_text(encoding="utf-8") if "--body-file" in argv else ""
log = Path(os.environ["GH_LOG"]); n = len(log.read_text(encoding="utf-8").splitlines()) + 1 if log.exists() else 1
with log.open("a", encoding="utf-8") as fh: fh.write(json.dumps({"argv": argv, "body": body}) + "\\n")
if os.environ.get("GH_FAIL_ON") and os.environ["GH_FAIL_ON"] in " ".join(argv):
    print("GraphQL: label not found", file=sys.stderr); sys.exit(1)
print(f"https://github.com/o/r/issues/{n}")
'''


def stub(tmp_path):
    inner = tmp_path / "gh_stub.py"
    inner.write_text(STUB_GH, encoding="utf-8")
    if os.name == "nt":
        s = tmp_path / "gh.cmd"
        s.write_text(f'@echo off\r\n"{sys.executable}" "{inner}" %*\r\n', encoding="utf-8")
    else:
        s = tmp_path / "gh"
        s.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{inner}' \"$@\"\n", encoding="utf-8")
        s.chmod(0o755)
    return s


def run(tmp_path, home, *extra, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(home)
    env["GH_LOG"] = str(tmp_path / "gh.log")
    env.update(env_extra or {})
    # Decode as UTF-8 explicitly: the CLI reconfigures its stdout to UTF-8 and
    # the titles carry `·`; `text=True` alone would read it with the Windows
    # locale and the assertions would see U+FFFD — the test_gate.py lesson.
    return subprocess.run([sys.executable, str(ISSUES), "widget", "--gh-cmd", str(stub(tmp_path)),
                           *extra], capture_output=True, text=True, encoding="utf-8", env=env)


def _records(tmp_path):
    log = tmp_path / "gh.log"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def calls(tmp_path):
    return [r["argv"] for r in _records(tmp_path)]


def bodies(tmp_path):
    return [r["body"] for r in _records(tmp_path)]


def test_dry_run_names_what_it_would_file_and_files_nothing(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Critical"), finding("W-F-2", "Minor"),
                                finding("W-F-3", "Major", status="resolved")])
    proc = run(tmp_path, home)
    assert proc.returncode == 0, proc.stderr
    assert "2 would be created" in proc.stdout
    assert "[Verdict] W-F-1 · Critical" in proc.stdout and "W-F-3" not in proc.stdout
    assert calls(tmp_path) == [], "dry run must not touch gh"
    assert not (home / "widget" / "issues.json").exists()


def test_create_files_open_findings_worst_first_and_records_the_ledger(tmp_path):
    home = make_home(tmp_path, [finding("W-F-2", "Minor"), finding("W-F-1", "Critical")])
    proc = run(tmp_path, home, "--create")
    assert proc.returncode == 0, proc.stderr
    made = calls(tmp_path)
    assert [c[c.index("--title") + 1] for c in made][0].startswith("[Verdict] W-F-1 · Critical")
    body = bodies(tmp_path)[0]
    assert "w-f-1.py:1 the defect" in body and "<!-- verdict-finding:W-F-1 -->" in body
    assert "--body-file" in made[0] and "--body" not in made[0], "the body travels as a file"
    ledger = json.loads((home / "widget" / "issues.json").read_text())
    assert ledger["W-F-1"]["number"] == 1 and ledger["W-F-2"]["number"] == 2
    assert ledger["W-F-1"]["url"].endswith("/issues/1")


def test_a_second_run_files_nothing_twice(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Critical")])
    assert run(tmp_path, home, "--create").returncode == 0
    proc = run(tmp_path, home, "--create")
    assert proc.returncode == 0 and "1 already filed" in proc.stdout
    assert len(calls(tmp_path)) == 1


def test_a_gh_failure_stops_keeps_earlier_successes_and_exits_1(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Critical"), finding("W-F-2", "Major"),
                                finding("W-F-3", "Minor")])
    proc = run(tmp_path, home, "--create", env_extra={"GH_FAIL_ON": "W-F-2"})
    assert proc.returncode == 1
    assert "stopped at W-F-2" in proc.stderr and "label not found" in proc.stderr
    ledger = json.loads((home / "widget" / "issues.json").read_text())
    assert set(ledger) == {"W-F-1"}, "the success before the failure is recorded, nothing after"
    proc = run(tmp_path, home, "--create")   # the failure cleared: continue where it stopped
    assert proc.returncode == 0
    assert set(json.loads((home / "widget" / "issues.json").read_text())) == {"W-F-1", "W-F-2", "W-F-3"}


def test_limit_files_the_worst_and_defers_the_rest(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Minor"), finding("W-F-2", "Blocker"),
                                finding("W-F-3", "Major")])
    proc = run(tmp_path, home, "--create", "--limit", "2")
    assert proc.returncode == 0, proc.stderr
    assert "created 2" in proc.stdout and "1 deferred" in proc.stdout
    assert set(json.loads((home / "widget" / "issues.json").read_text())) == {"W-F-2", "W-F-3"}


def test_labels_and_repo_reach_gh_verbatim(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Critical")])
    run(tmp_path, home, "--create", "--label", "verdict", "--label", "qa", "--repo", "o/r")
    c = calls(tmp_path)[0]
    assert c[c.index("--label") + 1] == "verdict" and "qa" in c and c[c.index("--repo") + 1] == "o/r"


def test_json_format(tmp_path):
    home = make_home(tmp_path, [finding("W-F-1", "Critical")])
    out = json.loads(run(tmp_path, home, "--format", "json").stdout)
    assert out["would_create"][0]["id"] == "W-F-1" and out["already_filed"] == 0


def test_no_state_is_exit_4(tmp_path):
    proc = run(tmp_path, tmp_path / "empty-home")
    assert proc.returncode == 4
