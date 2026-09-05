#!/usr/bin/env python3
"""Print the CHANGELOG section for one version — the body of its GitHub Release.

The release notes already exist: every version has a CHANGELOG entry in the
project's own voice, written before the tag. What was missing was the step
that puts them where a visitor looks first. The Releases page stopped at
v0.21.0 while the tags ran to v0.76.0, and a repository whose latest release
is fifty tags behind its code reads as abandoned.

Usage:
    python3 .github/release_notes.py 0.77.0          # the section, headline stripped
    python3 .github/release_notes.py v0.77.0 --title  # its one-line title only

Exit 1 with a message on stderr when the version has no section: a release
without notes is a claim, and the workflow that calls this refuses to make one.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)(?: — (\d{4}-\d{2}-\d{2}))?(?: · (.*))?$", re.M)


def section(version: str) -> tuple[str, str] | None:
    """(title, body) for `version`, or None when the changelog has no entry."""
    text = CHANGELOG.read_text(encoding="utf-8")
    heads = list(HEADING.finditer(text))
    for i, m in enumerate(heads):
        if m.group(1) != version:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].strip("\n")
        quote = (m.group(3) or "").strip().strip('"')
        title = f"v{version}" + (f" — {quote}" if quote else "")
        return title, body
    return None


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # The notes are full of em-dashes. On Windows the streams default to
        # the console codepage, the reader decodes UTF-8, and the notes die in
        # a reader thread that reports nothing — the same trap every CLI here
        # has hit once (gate.py, runner.py, accept.py).
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    want_title = "--title" in args
    args = [a for a in args if a != "--title"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    version = args[0].lstrip("v")
    found = section(version)
    if found is None:
        print(f"release_notes: CHANGELOG.md has no section for {version} — write the entry "
              "before tagging", file=sys.stderr)
        return 1
    title, body = found
    sys.stdout.write((title if want_title else body) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
