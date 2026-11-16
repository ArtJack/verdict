"""What verdict-local does with the profile's `site:` block: the browser pass, its findings
minted like any other, what it resolves by measurement, and the sentences it adds to the
judgment.

Split out of small.py before it landed (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and small.py imports back what run() calls.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    from . import browser
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser


def browser_pass(site, repo: Path, mint, findings_dir: Path, filed: list, facts: dict):
    """The profile's `site:` in a real browser: every finding minted like any other, the
    pass's own facts beside the gates'. → the pass, or None when the profile names no site."""
    if site is None:
        return None
    print("verdict-local: checking the site in a browser — "
          + ("a server started by the profile" if site.start else site.url), file=sys.stderr)
    site_pass = browser.browse(
        site, repo=repo,
        log=lambda message: print(f"verdict-local: {message}", file=sys.stderr),
        server_log=Path(tempfile.gettempdir()) / f"verdict-site-{os.getpid()}.log")
    for entry in site_pass.findings:
        mint(entry, findings_dir, filed)
    facts["site"] = site_pass.facts
    print(f"verdict-local: browser pass — {len(site_pass.facts.get('pages') or [])} page(s), "
          f"{len(site_pass.findings)} finding(s), {site_pass.facts.get('seconds', 0)} s, "
          "0 model calls", file=sys.stderr)
    return site_pass


def browser_resolved(site_pass, previous, on_record, resolved_ids: list,
                     still_open_ids: list) -> list:
    """A. again, for what a browser measured: a prior browser finding whose every page this
    pass measured with the same check, and which it did not find again, is gone by
    measurement — moved from `still_open_ids` to `resolved_ids` here. A page not reached, or a
    check that could not finish, leaves it where it was."""
    if site_pass is None:
        return []
    moved = []
    refound = {fid for fid, _status in on_record}
    for fid in browser.resolved_by_measurement(previous, site_pass.measured, refound):
        if fid in still_open_ids:
            still_open_ids.remove(fid)
            resolved_ids.append(fid)
            moved.append(fid)
    return moved


def browser_not_tested(site_pass) -> list:
    return [] if site_pass is None else [f"browser pass: {line}" for line in site_pass.not_tested]


def browser_prose(site_pass, resolved: list) -> tuple:
    """(a sentence for the scope, a sentence for the notes) — empty without a site."""
    if site_pass is None:
        return "", ""
    scope = (f" A browser checked {len(site_pass.facts.get('pages') or [])} page(s) of the site "
             f"in {site_pass.facts.get('browser', 'no browser')}, GET requests only, with no "
             "model; what it filed it measured, so it is filed `proven`.")
    notes = (f" Resolved by measurement in the browser, every page each was filed on checked "
             f"again: {', '.join(resolved)}." if resolved else "")
    return scope, notes
