"""The release workflow's supply-chain shape, written down where a test can read it.

VERDICT-F-73: the registry job downloaded and executed a third-party binary
from a `releases/latest` URL, with no checksum, in a job holding an OIDC
identity — and `continue-on-error` would have hidden what a substituted
binary did. The fix is a pin and a checksum; this is what keeps the pin from
quietly reverting to `latest` in a later edit.
"""

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml"


def _registry_job() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("\n  mcp-registry:")
    nxt = re.search(r"\n  [a-z-]+:\n", text[start + 1:])
    return text[start:] if nxt is None else text[start:start + 1 + nxt.start()]


def _commands(job: str) -> str:
    """The lines that run — comments explaining what NOT to do are not evidence."""
    return "\n".join(line for line in job.splitlines() if not line.lstrip().startswith("#"))


def test_the_publisher_is_pinned_to_a_release_not_to_latest():
    job = _commands(_registry_job())
    assert "releases/latest" not in job, "a `latest` download runs whatever is published next"
    assert re.search(r"MCP_PUBLISHER_VERSION:\s*v\d+\.\d+\.\d+", job), "no pinned version"


def test_the_download_is_checksummed_before_it_runs():
    job = _registry_job()
    m = re.search(r"MCP_PUBLISHER_SHA256:\s*([0-9a-f]{64})\b", job)
    assert m, "no sha256 pinned beside the version"
    assert "sha256sum -c" in job, "the checksum is declared but never checked"
    checked = job.index("sha256sum -c")
    executed = job.index("./mcp-publisher --version")
    assert checked < executed, "the binary runs before its checksum is verified"


def test_a_registry_failure_is_visible():
    """A job that hands an OIDC identity to a downloaded binary must not also
    swallow what the binary did."""
    job = _registry_job()
    assert "continue-on-error" not in job
    assert "::error::" in job and "exit 1" in job, "the PyPI wait no longer fails when PyPI never answers"


def test_the_job_holds_no_more_than_it_needs():
    job = _registry_job()
    perms = job[job.index("permissions:"):job.index("steps:")]
    assert "id-token: write" in perms and "contents: read" in perms
    assert "contents: write" not in perms and "packages" not in perms
