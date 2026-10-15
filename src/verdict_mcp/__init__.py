"""verdict-mcp: read-only MCP server over Verdict QA state."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read from the installed distribution rather than restating it. The
    # hardcoded copy that lived here said 0.2.0 while plugin.json and
    # pyproject.toml said 0.24.0 — a third place to remember at release time
    # is a third place to forget.
    # The distribution name, not the import name — they differ on purpose
    # (see the comment in pyproject.toml). Renaming one without the other
    # sends this straight down the PackageNotFoundError path, where a real
    # install would silently report itself as "0+unknown".
    __version__ = version("verdict-qa-mcp")
except PackageNotFoundError:            # running from a checkout or the plugin cache
    # The common stranger path: `python3 <plugin-root>/src/verdict_mcp/harness.py`
    # with nothing installed. The plugin manifest two levels up IS the
    # version of this code; "0+unknown" is for when even that is missing.
    import json as _json
    from pathlib import Path as _Path
    try:
        _manifest = _Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
        __version__ = str(_json.loads(_manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, IndexError):
        __version__ = "0+unknown"
