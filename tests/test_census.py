"""Tests for the code censuses — the measurable half of AI-code review.

The censuses exist because some AI-failure signatures are mechanically
countable, and the standing rule is that what can be measured is never left to
the model to notice. What these tests mostly guard is restraint: a census that
over-claims (flagging declared deps, stdlib, local modules) would train the
reader to ignore it, which is worse than not having it.
"""

import json
import subprocess

import pytest

from verdict_mcp.census import (
    code_census, imports_census, placeholders_census, provenance_census)


def git(args, cwd, message_env=None):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "app"
    r.mkdir()
    git(["init", "-qb", "main"], r)
    (r / "requirements.txt").write_text("requests\nPyYAML\n", encoding="utf-8")
    (r / "app.py").write_text("import requests\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "first"], r)
    return r


def lines_of(*items):
    return [(path, i + 1, text) for path, i, text in items]


# ── imports: candidates, not convictions ──────────────────────────────────

def test_an_undeclared_import_is_flagged_with_its_location(repo):
    out = imports_census(repo, [("net.py", 2, "import backoff")])
    assert out["undeclared"] == {"backoff": ["net.py:2"]}


def test_declared_stdlib_and_local_modules_are_never_flagged(repo):
    (repo / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    out = imports_census(repo, [
        ("a.py", 1, "import requests"),      # declared
        ("a.py", 2, "import json"),          # stdlib
        ("a.py", 3, "import helpers"),       # local module
        ("a.py", 4, "from app import main"),  # local file
    ])
    assert out["undeclared"] == {}


def test_the_famous_name_mismatches_do_not_false_positive(repo):
    """`import yaml` is satisfied by PyYAML; flagging it would teach the reader
    to ignore the census."""
    out = imports_census(repo, [("a.py", 1, "import yaml")])
    assert out["undeclared"] == {}


def test_js_imports_are_checked_against_package_json(repo):
    (repo / "package.json").write_text(json.dumps(
        {"dependencies": {"express": "^4"}}), encoding="utf-8")
    out = imports_census(repo, [
        ("srv.js", 1, "const express = require('express')"),
        ("srv.js", 2, "import leftpad from 'leftpad'"),
        ("srv.js", 3, "import util from './util'"),   # relative = local
    ])
    assert out["undeclared"] == {"leftpad": ["srv.js:2"]}


def test_the_caveat_travels_with_the_data(repo):
    assert "candidates" in imports_census(repo, [])["caveat"]


# ── placeholders and swallows ─────────────────────────────────────────────

def test_the_two_line_swallow_is_caught_only_when_the_lines_are_adjacent():
    hits = placeholders_census([
        ("a.py", 5, "    except Exception:"),
        ("a.py", 6, "        pass"),
    ])
    assert hits["counts"]["swallowed_except"] == 1
    # a diff that added the except and, twenty lines later, an unrelated pass
    # is not a swallow
    apart = placeholders_census([
        ("a.py", 5, "    except Exception:"),
        ("a.py", 25, "        pass"),
    ])
    assert "swallowed_except" not in apart["counts"]


def test_markers_are_counted_with_samples():
    hits = placeholders_census([
        ("a.py", 1, "# TODO: real API"),
        ("b.js", 2, "value = 5.0  # for now"),
        ("c.js", 3, "promise.catch(() => {})"),
    ])
    assert hits["counts"] == {"todo": 1, "for_now": 1, "swallowed_catch": 1}
    assert hits["samples"]["todo"] == ["a.py:1 # TODO: real API"]


# ── provenance: measured, with its own caveat ─────────────────────────────

def test_ai_trailers_are_counted_over_the_range(repo):
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "add b\n\nCo-Authored-By: Claude <noreply@anthropic.com>"], repo)
    out = provenance_census(repo, f"{base}..HEAD")
    assert out["commits"] == 1 and out["ai_attributed"] == 1
    assert "not evidence of human authorship" in out["caveat"]


def test_no_range_falls_back_to_recent_history(repo):
    out = provenance_census(repo, None)
    assert out["scope"] == "last 30 commits" and out["commits"] == 1


# ── the assembled block ───────────────────────────────────────────────────

def test_code_census_scopes_itself_to_the_diff_when_there_is_one(repo):
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    (repo / "net.py").write_text(
        "import backoff\ntry:\n    x = 1\nexcept Exception:\n    pass\n",
        encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "net"], repo)
    out = code_census(repo, f"{base}..HEAD")
    assert out["scope"].startswith("lines added in")
    assert "backoff" in out["imports"]["undeclared"]
    assert out["placeholders"]["counts"]["swallowed_except"] == 1
    # app.py's pre-existing `import requests` is outside the range: not scanned
    assert "requests" not in out["imports"]["undeclared"]


def test_code_census_on_a_baseline_scans_the_tree_and_says_so(repo):
    out = code_census(repo, None)
    assert out["scope"].startswith("tree scan of")
    assert "leads, not findings" in out["reading"]
