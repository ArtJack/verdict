"""The shipped command set is a contract, not a directory listing.

Three things drift silently and were each caught by hand rather than by a test:
the README's command table falling behind `commands/`, a command file losing the
front matter that makes it selectable, and the eval harness provisioning a file
under one name while invoking another. A stale row in the table is not cosmetic —
it is a documented command that answers `Unknown command`, which reads to a user
as the plugin being broken.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COMMANDS = REPO / "commands"


def shipped() -> set[str]:
    return {p.stem for p in COMMANDS.glob("*.md")}


def documented() -> set[str]:
    """Command names in the README's `| /verdict:name |` table rows."""
    names = set()
    for line in (REPO / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| `/verdict:"):
            names.add(line.split("`/verdict:", 1)[1].split("`", 1)[0])
    return names


def test_readme_table_matches_shipped_commands():
    missing, stale = shipped() - documented(), documented() - shipped()
    assert not missing, f"shipped but undocumented: {sorted(missing)}"
    assert not stale, f"documented but not shipped — types as Unknown command: {sorted(stale)}"


def test_run_is_the_front_door():
    assert "run" in shipped(), "the front door is /verdict:run"


@pytest.mark.parametrize("path", sorted(COMMANDS.glob("*.md")), ids=lambda p: p.stem)
def test_command_has_front_matter(path: Path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: no front matter"
    fm = text.split("---\n", 2)[1]
    assert "description:" in fm, f"{path.name}: no description — unselectable in the picker"
    assert "argument-hint:" in fm, f"{path.name}: no argument-hint"


@pytest.mark.parametrize("path", sorted(COMMANDS.glob("*.md")), ids=lambda p: p.stem)
def test_command_references_resolve(path: Path):
    """A command pointing at a sibling that no longer exists routes into a dead end."""
    import re
    for ref in set(re.findall(r"`/verdict:([a-z-]+)`", path.read_text(encoding="utf-8"))):
        assert ref in shipped(), f"{path.name} routes to /verdict:{ref}, which is not shipped"


def test_no_stale_command_names_outside_history():
    """CHANGELOG and dated eval results record the names used at the time; live docs must not."""
    live = [REPO / "README.md", REPO / "agents" / "verdict.md",
            REPO / "docs" / "nightly.md", *COMMANDS.glob("*.md")]
    for f in live:
        text = f.read_text(encoding="utf-8")
        assert "/qa-" not in text, f"{f.relative_to(REPO)}: stale /qa- command name"
        assert "/verdict:qa-" not in text, f"{f.relative_to(REPO)}: stale /verdict:qa- name"
