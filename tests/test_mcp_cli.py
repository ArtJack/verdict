"""`verdict-mcp --help` answers instead of waiting on stdin.

It started the server and sat on stdin: the first command a stranger types,
blocking with no output — still alive after seven minutes in the fresh-install
run of the 2026-10-02 audit (D-D-10).
"""

import subprocess
import sys

from verdict_mcp import __version__


def _run(*args):
    return subprocess.run([sys.executable, "-m", "verdict_mcp.server", *args],
                          capture_output=True, text=True, timeout=30)


def test_help_prints_usage_and_exits():
    proc = _run("--help")
    assert proc.returncode == 0
    assert "verdict-mcp" in proc.stdout and "MCP server" in proc.stdout
    assert "claude mcp add" in proc.stdout


def test_version_names_the_distribution():
    proc = _run("--version")
    assert proc.returncode == 0 and __version__ in proc.stdout
