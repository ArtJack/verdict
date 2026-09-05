"""One version line, three manifests.

`pyproject.toml` (PyPI), `.claude-plugin/plugin.json` (the plugin) and
`server.json` (the MCP Server Registry) each carry the version, and each has
drifted at least once: #56 bumped pyproject without plugin.json, and the
registry entry sat three releases behind while the code moved. release.yml
refuses a tag that disagrees with the first two; this refuses a commit in
which any of the three disagrees, before there is a tag to refuse.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def versions(root: Path) -> dict:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    return {
        "pyproject.toml": re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1),
        ".claude-plugin/plugin.json": plugin["version"],
        "server.json": server["version"],
        "server.json packages[0]": server["packages"][0]["version"],
    }


def agree(root: Path) -> bool:
    return len(set(versions(root).values())) == 1


def test_the_three_manifests_carry_one_version():
    assert agree(REPO), f"the manifests disagree: {versions(REPO)}"


def test_the_version_is_a_release_number():
    """Not a placeholder, not a dev suffix: the tag guard compares it literally."""
    for name, v in versions(REPO).items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"{name} carries {v!r}"


def _manifests(root: Path, pyproject: str, plugin: str, server: str, package: str):
    (root / ".claude-plugin").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{pyproject}"\n',
                                         encoding="utf-8")
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "x", "version": plugin}), encoding="utf-8")
    (root / "server.json").write_text(
        json.dumps({"version": server, "packages": [{"version": package}]}), encoding="utf-8")


def test_the_check_can_fail(tmp_path):
    """The instrument, controlled: a registry entry left behind — the drift
    that actually happened — must be seen, and agreement must be seen too."""
    _manifests(tmp_path, "0.77.0", "0.77.0", "0.73.0", "0.73.0")
    assert not agree(tmp_path)
    ok = tmp_path / "ok"
    ok.mkdir()
    _manifests(ok, "0.77.0", "0.77.0", "0.77.0", "0.77.0")
    assert agree(ok)
