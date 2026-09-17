"""Nothing the tester is handed may tell it that it is being evaluated.

`eval/run_eval.py` copies a fixture into a scratch repository and the tester reads all of
it. Every fixture README carried a line like "It intentionally contains seeded defects —
see `../../expected-liar.json` for the answer key (do not read it during an eval run)",
and on 2026-09-17 a paid Opus run quoted it back: *"the agent noticed an answer key at
`../../expected-liar.json`. So the defects are planted fixtures, not a real product
regression — which bears directly on its LIAR-Q-1 and LIAR-Q-2."* The key itself was
never copied and could not be read; the sentence was enough. A tester that knows it is
being graded on seeded defects is not the tester a user gets.

So this builds what the harness builds — every fixture, the golden state the seeded mode
plants, the rev-B commit, and the mutation run's checkout — with no model and no tokens,
and reads it the way the tester would: every line any commit ever added, every file name,
every commit message and identity, the planted QA state, and the names of the directories
themselves.

Maintainer notes belong in `eval/README.md`, which is not copied anywhere.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
EVAL = REPO / "eval"
sys.path.insert(0, str(EVAL))

import run_eval  # noqa: E402
import run_mutation  # noqa: E402
from mutate import generate  # noqa: E402

# What an eval says about itself, and where its keys live. `\bevals?\b` rather than the
# bare phrase "eval run": the sentence above is one of six spellings the fixtures used,
# and "eval fixture", "delta eval", "verdict-eval" and "eval/mutate.py" are the others.
GIVEAWAYS = (
    re.compile(r"expected-", re.I),                  # expected-liar.json, EXPECTED-DELTA.md
    re.compile(r"EXPECTED"),                         # EXPECTED.md — the human keys
    re.compile(r"expected\.json", re.I),
    re.compile(r"expected\*", re.I),                 # "do not read any `expected*` file"
    re.compile(r"answer[ _-]?keys?", re.I),
    re.compile(r"\bevals?\b", re.I),
    re.compile(r"\bseeded\b", re.I),
    re.compile(r"\bplanted\b", re.I),
    re.compile(r"\bmutants?\b", re.I),
    re.compile(r"\bmutation\b", re.I),
    # "fixture rev A", "the fixture under test", "Unlike the `pricer` fixture". The
    # plural is the fictional project's own `fixtures/` test data and never matches;
    # `pytest.fixture` is a real project's vocabulary.
    re.compile(r"(?<!pytest\.)\bfixture\b", re.I),
)

# A word that says what a directory is FOR rather than what the project IS. The name
# becomes the project key, the QA root and the prefix of every finding id, so the liar
# fixture's checkout handed its tester `LIAR-Q-1` to quote.
ROLE_WORDS = ("eval", "fixture", "golden", "seed", "plant", "mutant", "mutation", "clean",
              "liar", "slop", "trap", "decoy", "control", "adversarial")

# Tool droppings from the maintainer's own working tree. `copytree` copied them as they
# lay: pytest's `lastfailed`, which names the four red tests, and a stale
# `pricer_clean/__pycache__/pricer.pyc` still carrying the docstring the source had
# stopped saying. Never reproducible in CI, which is exactly why it went unnoticed.
BYPRODUCTS = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
              ".hypothesis", "node_modules", ".coverage", ".DS_Store")

# (where, the matched word) → why it is the fictional project's own vocabulary.
# An entry that stops matching is deleted, not kept: see the last test in this file.
ALLOWED = {
    ("pricer:CHANGELOG.md", "fixture"):
        "the project's own test data — `fixtures/bulk_orders.json`, added in rev B",
    ("pricer:qa/profile.md", "fixture"):
        "the same test data, which the tester is forbidden to create for itself",
    ("pricer:qa/reports/2026-08-24-run2-delta.md", "fixture"):
        "the tester's own run-2 finding about the test that reads that data",
}


def _git(repo, args) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout


def _readable(repo) -> list:
    """(where, text) for everything `git log` shows a tester about this repository.

    Identities and messages, every line any commit ever added, and every file name any
    commit ever carried — history, not just the current tree, because `git log -p` and
    `git show` are the first things a delta or root-cause run reaches for. `.claude/` is
    excluded: the provisioned contract and hook wiring are the product under test, they
    are identical in production, and they carry this repository's absolute path.
    """
    out = []
    record, field = "\x1e", "\x1f"
    log = _git(repo, ["log", "--all", "--no-color",
                      f"--format={record}%an <%ae>%n%cn <%ce>%n%B{field}", "-p",
                      "--", ".", ":(exclude).claude"])
    for i, entry in enumerate(c for c in log.split(record) if c.strip()):
        head, _, diff = entry.partition(field)
        out.append((f"commit {i}", head))
        path = "?"
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                path = line[len("+++ b/"):]
                out.append((path, path))          # a file name is text the tester reads
            elif line.startswith("Binary files"):
                out.append((path, line))
            elif line.startswith("+") and not line.startswith("+++"):
                out.append((path, line[1:]))
    return out


def _on_disk(root: Path) -> list:
    """(where, text) for a tree the tester reads but git does not track — the QA state
    the seeded mode plants as the tester's own memory of the project."""
    out = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        out.append((rel, rel))
        out.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    return out


def _giveaways(where: str, text: str) -> list:
    """Every giveaway in one piece of text, minus what the allowlist excuses."""
    found = []
    for pattern in GIVEAWAYS:
        for match in pattern.finditer(text):
            word = match.group(0)
            if (where, word) in ALLOWED or (where, word.lower()) in ALLOWED:
                continue
            line = text[text.rfind("\n", 0, match.start()) + 1:]
            line = line[:line.find("\n") if "\n" in line else len(line)]
            found.append((where, word, line.strip()[:120]))
    return found


def _build_fixture(key: str, fixture: dict, root: Path, env: dict) -> dict:
    """One fixture, staged exactly as `run_once` stages it: rev A, then — where the
    fixture has a delta mode — the golden state and rev B."""
    work = root / key
    checkout = work / run_eval.checkout_name(fixture)
    qa_root = work / "qa-home" / run_eval.checkout_name(fixture)
    rev_a = run_eval.stage_rev_a(checkout, fixture, env)
    planted = None
    if "seeded" in fixture["modes"]:
        run_eval.plant_golden(qa_root, checkout, rev_a)
        planted = qa_root
    if {"seeded", "live"} & set(fixture["modes"]):
        run_eval.stage_rev_b(checkout, env)
    return {"key": key, "checkout": checkout, "planted": planted}


def _build_mutation(root: Path, env: dict) -> dict:
    """The mutation run's checkout: the base with one line broken."""
    fixture_dir = EVAL / "fixtures" / "pricer_clean"
    mutant = generate((fixture_dir / "pricer.py").read_text(encoding="utf-8"))[0]
    checkout, _, _ = run_mutation.stage(mutant, fixture_dir, "pricer.py",
                                        root / "mutation", env)
    return {"key": "mutation", "checkout": checkout, "planted": None}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Every checkout the harness hands a tester, built once. No model, no tokens."""
    root = tmp_path_factory.mktemp("staged")
    env = dict(os.environ)
    staged = [_build_fixture(key, fixture, root, env)
              for key, fixture in sorted(run_eval.FIXTURES.items())]
    staged.append(_build_mutation(root, env))
    return staged


def _everything(staged: dict) -> list:
    readable = [(f"{staged['key']}:{where}", text)
                for where, text in _readable(staged["checkout"])]
    if staged["planted"]:
        readable += [(f"{staged['key']}:qa/{where}", text)
                     for where, text in _on_disk(staged["planted"])]
    return readable


def test_nothing_the_tester_is_handed_names_the_eval(built):
    found = []
    for staged in built:
        for where, text in _everything(staged):
            found += _giveaways(where, text)
    assert not found, (
        "the checkout tells the tester it is being evaluated:\n"
        + "\n".join(f"  {where}: {word!r} in {line!r}" for where, word, line in found)
        + "\nMove the note to eval/README.md, which is copied nowhere. If the word is "
          "genuinely the fictional project's, add (where, word) to ALLOWED with the "
          "reason.")


def test_the_patterns_catch_what_they_were_written_for():
    """The control: without it, a scanner that matched nothing would pass every tree.
    These four are verbatim what the fixtures and the harness said before 2026-09-17."""
    for text in ("It intentionally contains seeded defects — see `../../EXPECTED.md` "
                 "for the answer key (do not read it during an eval run).",
                 "fixture rev A",
                 "verdict-eval <eval@verdict>",
                 "It exists to be broken one line at a time by `eval/mutate.py`"):
        assert _giveaways("nowhere", text), text


def test_the_checkout_is_named_for_the_project_not_its_role(built):
    for staged in built:
        name = staged["checkout"].name
        assert not _giveaways(f"{staged['key']}:<name>", name), name
        role = [word for word in ROLE_WORDS if word in name.lower()]
        assert not role, (
            f"the checkout {name!r} is named for {role} — the tester reads the name as "
            f"its project key and stamps it on every finding id it files")


def test_the_scratch_directory_is_named_by_the_platform_not_the_harness():
    """`verdict-eval-` and `verdict-mut-M03-` put the eval, its protocol and the mutant's
    own id into every absolute path the tester wrote into its evidence."""
    scratch = run_eval.scratch_dir()
    try:
        assert scratch.name.startswith(tempfile.gettempprefix())
        assert not [w for w in ROLE_WORDS if w in scratch.name.lower()]
    finally:
        scratch.rmdir()


def test_no_byproduct_of_the_maintainers_own_tree_reaches_the_tester(built):
    """Vacuous in CI, where nothing has ever run in `eval/fixtures/` — which is why the
    mechanism is tested below as well as the result here."""
    for staged in built:
        paths = _git(staged["checkout"], ["ls-files"]).split("\n")
        dropped = [p for p in paths if any(b in p for b in BYPRODUCTS)]
        assert not dropped, f"{staged['key']}: {dropped}"
        assert _git(staged["checkout"], ["status", "--porcelain"]) == "", (
            f"{staged['key']}: the tester's first `git status` is not clean, so its "
            f"profile's isolation check fails on the harness's own leftovers")


def test_a_fixture_is_copied_as_git_sees_it(tmp_path):
    """The mechanism: tracked files and untracked ones `.gitignore` does not exclude,
    and nothing else. A denylist of byproduct names would have to be complete; this
    borrows the definition the repository already uses."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "__pycache__").mkdir(parents=True)
    (src / ".pytest_cache" / "v").mkdir(parents=True)
    (src / "app.py").write_text("x = 1\n", encoding="utf-8")
    (src / "notes.md").write_text("untracked but not ignored\n", encoding="utf-8")
    (src / "probe.py").write_text("print('fingerprint')\n", encoding="utf-8")
    (src / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (src / "__pycache__" / "app.pyc").write_bytes(b"stale docstring")
    (src / ".pytest_cache" / "v" / "lastfailed").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(src),
                    "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(src), "add", "app.py", ".gitignore"], check=True,
                   capture_output=True)

    run_eval.overlay(src, dst, exclude=("probe.py",))
    assert sorted(p.name for p in dst.rglob("*") if p.is_file()) == [
        ".gitignore", "app.py", "notes.md"]


def test_every_allowlist_entry_is_still_needed(built):
    """An entry that matches nothing is a hole standing open in the scanner."""
    hit = set()
    for staged in built:
        for where, text in _everything(staged):
            for (allowed_where, word), _ in ALLOWED.items():
                if where == allowed_where and re.search(re.escape(word), text, re.I):
                    hit.add((allowed_where, word))
    assert set(ALLOWED) == hit, f"stale allowlist entries: {sorted(set(ALLOWED) - hit)}"
