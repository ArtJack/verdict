"""verdict-mcp: read-only MCP server over Verdict QA state."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read from the installed distribution rather than restating it. The
    # hardcoded copy that lived here said 0.2.0 while plugin.json and
    # pyproject.toml said 0.24.0 — a third place to remember at release time
    # is a third place to forget.
    __version__ = version("verdict-mcp")
except PackageNotFoundError:            # running from a checkout, not installed
    __version__ = "0+unknown"
