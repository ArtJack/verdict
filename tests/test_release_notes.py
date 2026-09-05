"""`.github/release_notes.py` — the CHANGELOG section that becomes a GitHub Release.

The notes have always existed; the Releases page stopped at v0.21.0 anyway,
because nothing carried them there. The workflow now refuses to tag a version
without a section, and this is the reader it trusts to find one.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".github"))

import release_notes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".github" / "release_notes.py"


def _newest_version() -> str:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return release_notes.HEADING.search(text).group(1)


def test_the_newest_changelog_entry_is_readable():
    """The control: the section this release will publish must be found and be
    more than a heading."""
    found = release_notes.section(_newest_version())
    assert found is not None
    title, body = found
    assert title.startswith(f"v{_newest_version()}")
    assert len(body.split()) > 40, "a release note is a paragraph, not a line"


def test_the_body_stops_at_the_next_heading():
    title, body = release_notes.section("0.77.0")
    assert "the harness stops guessing" in title
    assert "## 0.76.0" not in body and "VERDICT-F-26" in body


def test_a_version_without_a_section_is_refused():
    assert release_notes.section("0.0.0") is None
    proc = subprocess.run([sys.executable, str(SCRIPT), "0.0.0"], capture_output=True,
                          text=True, encoding="utf-8")
    assert proc.returncode == 1 and "no section" in proc.stderr


def test_the_cli_prints_body_or_title(tmp_path):
    body = subprocess.run([sys.executable, str(SCRIPT), "v0.77.0"], capture_output=True,
                          text=True, encoding="utf-8")
    assert body.returncode == 0 and "VERDICT-F-26" in body.stdout
    title = subprocess.run([sys.executable, str(SCRIPT), "0.77.0", "--title"],
                           capture_output=True, text=True, encoding="utf-8")
    assert title.stdout.strip() == "v0.77.0 — the harness stops guessing"


def test_every_tag_shaped_heading_parses():
    """A heading the regex cannot read is a release the workflow cannot make."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    shouty = [line for line in text.splitlines() if line.startswith("## ")]
    parsed = [m.group(1) for m in release_notes.HEADING.finditer(text)]
    assert len(parsed) == len(shouty), (
        f"{len(shouty) - len(parsed)} '## ' heading(s) in CHANGELOG.md do not parse as a version")
