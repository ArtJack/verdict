"""The Claude directory reads every file this plugin ships, tests included.

The directory serves the plugin from this repository's default branch, and every
version after v0.90.2 · 274a72b was held there (found 2026-10-03), for two reasons
nothing in this suite looked at:

* **"Secret in a shipped file: tests/test_hygiene.py".** The hygiene scanner's own
  tests carry the shapes it detects. Fake keys split as `"sk_" + "live_" + …`, or as
  adjacent literals, are still keys to a scanner that joins strings the way Python
  does, and twelve such values sat in six test files. They are stored reversed now
  (`test_hygiene.unseen`).
* **"Files or downloads the validator couldn't inspect: CHANGELOG.md".** The 0.90.3
  entry took the changelog from 250 KB, which was read, to 267 KB, which was not.
  Releases before 0.77.0 moved to `docs/changelog/`.

Both are properties of the whole tree, so both are checked over every tracked file.
The size line sits below the limit on purpose: a file that grows toward it fails here
first, while there is still room to split it.
"""

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Measured, not documented: 250,417 bytes was read and 267,029 was held. The limit
# is most likely 256 KiB; failing at 240 KiB leaves room to act.
SIZE_LINE = 240 * 1024

# Common key shapes, as a secret scanner matches them. A value that matches any of
# these after Python-style joining is what got the directory to refuse a version.
SHAPES = {
    "anthropic": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai": r"sk-(?:proj-)?[A-Za-z0-9]{32,}",
    "aws-access-key": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "github": r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}",
    "gitlab": r"glpat-[A-Za-z0-9_\-]{20}",
    "slack": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    "slack-webhook": r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}",
    "stripe": r"(?:sk|rk)_live_[A-Za-z0-9]{16,}",
    "google-api": r"AIza[0-9A-Za-z_\-]{35}",
    "sendgrid": r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}",
    "twilio": r"\bSK[0-9a-fA-F]{32}\b",
    "npm": r"npm_[A-Za-z0-9]{36}",
    "pypi": r"pypi-AgE[A-Za-z0-9_\-]{50,}",
    "huggingface": r"hf_[A-Za-z0-9]{30,}",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt": r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "db-url-credential": r"(?i:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/'\"]+:[^@\s'\"]{6,}@",
}
SHAPE = re.compile("|".join(f"(?P<{k.replace('-', '_')}>{p})" for k, p in SHAPES.items()))


def tracked_files():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout: the directory reads the repository, so this needs one")
    return [REPO / p for p in out.decode("utf-8").split("\0") if p]


def _folded(node):
    """A string a parser-aware scanner can assemble: a literal (adjacent literals are
    already one), an f-string's literal parts, or a `+` chain of those. None when any
    piece is computed at run time."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "\0" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left), _folded(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def secret_shapes(path: Path):
    """(line, shape) for every key-shaped value in a file: its raw text, and for Python
    every string as the parser assembles it."""
    text = path.read_bytes().decode("utf-8", errors="ignore")
    pieces = [(None, text)]
    if path.suffix == ".py":
        try:
            pieces += [(getattr(n, "lineno", 0), s) for n in ast.walk(ast.parse(text))
                       if (s := _folded(n))]
        except (SyntaxError, ValueError):
            pass            # a fixture that is not valid Python is still scanned as text
    found = set()
    for line, piece in pieces:
        for m in SHAPE.finditer(piece):
            at = line if line is not None else text.count("\n", 0, m.start()) + 1
            found.add((at, m.lastgroup))
    return sorted(found)


def test_no_shipped_file_carries_a_key_shaped_value():
    hits = [f"{p.relative_to(REPO).as_posix()}:{line} ({shape})"
            for p in tracked_files() if p.is_file() for line, shape in secret_shapes(p)]
    assert hits == [], ("the directory refuses a version that ships these, fake or not — store "
                        "test data reversed (tests/test_hygiene.py::unseen):\n  " + "\n  ".join(hits))


def test_the_check_sees_a_key_split_the_way_python_joins_it(tmp_path):
    """The control: a split key is still found, and a reversed one is not."""
    stripe = "".join(reversed("_evil_ks"))    # built at run time, so this file stays clean
    planted = tmp_path / "fixture.py"
    planted.write_text(f'A = "{stripe[:3]}" "{stripe[3:]}" + "{"Q" * 24}"\n'
                       f'B = "{"".join(reversed(stripe + "Q" * 24))}"[::-1]\n', encoding="utf-8")
    assert [shape for _, shape in secret_shapes(planted)] == ["stripe"]


def test_no_shipped_file_is_too_large_for_the_directory_to_read():
    big = sorted(((p.stat().st_size, p.relative_to(REPO).as_posix()) for p in tracked_files()
                  if p.is_file() and p.stat().st_size > SIZE_LINE), reverse=True)
    assert big == [], (f"over {SIZE_LINE // 1024} KiB, close to the size the directory stops "
                       f"reading at — split the file: {big}")
