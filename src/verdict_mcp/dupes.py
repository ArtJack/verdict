"""verdict-dupes — the tracker search a report should never skip.

Before the 2026-10-16/17 stranger reports went out, each finding was searched by hand in the
repository's issues and pull requests; two of the nine were already fixed by open PRs
(fava #2381, numpy-financial #158) and were not reported. This is that search as a command.

For each open Major+ finding (or the ids named), up to six single-term queries — the code
names in its title, its title's distinctive words, the names and file stems its evidence cites
— run against the repository's GitHub tracker through `gh search issues --include-prs` (one
word per query: the tracker's search is an AND over words, and two words together found
nothing on 2026-10-17 where one found the fix). Items are ranked by how many terms returned
them and by title overlap; the top five go to `<qa-root>/related.jsonl`, outside the signed
row, and `verdict-gate` shows each finding's first related item. A related item is a lead for
the person writing the report, never a resolution: the finding stays open.

Needs `gh` logged in. Exit 0: every finding searched; 2: nothing could be searched.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from . import clock
    from .state import is_open, load_state, repo_for_root
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from state import is_open, load_state, repo_for_root

RELATED_FILE = "related.jsonl"
SEVERITIES_ASKED = ("Blocker", "Critical", "Major")
MAX_TERMS = 6
LIMIT = 15
KEEP = 5
PAUSE_S = 2.2            # the search API allows 30 requests a minute to a logged-in user
STOP = set("""
a an and are as at be because but by can could does for from has have if in into is it its
of on or so than that the their then there these they this those to was were when where which
while with without would about after before again all also any both each every more most
not only other over same some such under until very will yes
instead returns return returning value values result results wrong incorrect error errors
fails failed failing bug issue function method call calls called make makes made case cases
data file line lines code test tests check checks should never always still even
""".split())
CODE_NOISE = set("""
self cls none true false return import def class print assert isinstance str int float dict
list set tuple bool bytes decimal object type len range super lambda yield raise except try
with pass break continue else elif while for in not and or is if as from global nonlocal
await async del compile match re os sys path json
""".split())
_SOURCE = re.compile(r"([\w./\\-]+)\.(?:py|pyi|ts|tsx|js|jsx|mjs|go|rs|rb|java|kt|cs|php|c|cc|cpp|h|swift)\b")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_REMOTE = re.compile(r"(?:github\.com[:/])([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def wants_search(finding: dict) -> bool:
    return is_open(finding) and str(finding.get("severity") or "") in SEVERITIES_ASKED


def _code_names(text: str) -> list[str]:
    """Identifiers inside backticks, in order, without the language's own words."""
    names = []
    for span in re.findall(r"`([^`]{1,120})`", text):
        for name in _NAME.findall(span):
            if len(name) < 4 or name.lower() in CODE_NOISE or name.lower() in STOP or name in names:
                continue
            names.append(name)
    return names


def _title_words(title: str) -> list[str]:
    """Distinctive words of the title, code spans removed, longest first."""
    plain = re.sub(r"`[^`]*`", " ", title).replace("-", " ")   # the tracker splits on hyphens
    seen, words = set(), []
    for w in re.findall(r"[A-Za-z]{4,}", plain):
        lw = w.lower()
        if len(lw) < 5 or lw in STOP or lw in seen:
            continue
        seen.add(lw)
        words.append(lw)
    return sorted(words, key=lambda w: (-len(w), words.index(w)))


def _stems(evidence: list) -> list[str]:
    stems = []
    for e in evidence:
        for m in _SOURCE.finditer(str(e)):
            stem = Path(m.group(1).replace("\\", "/")).name.strip("_")
            if len(stem) >= 4 and stem not in ("init", "main", "test", "tests", "conftest",
                                                "index", "utils", "setup") \
                    and not stem.startswith("test_") and stem not in stems:
                stems.append(stem)
    return stems


_SYMPTOM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)*%?(?![\w.])|\b(?:NaN|nan|inf|Infinity|null|None|undefined)\b")
TITLE_WEIGHT, EVIDENCE_WEIGHT, SYMPTOM_WEIGHT = 1.0, 0.5, 2.5


def _symptoms(text: str) -> set:
    """The numbers and the special values a title states — `-100%`, `-1.0`, `NaN` — the tokens
    two descriptions of one defect share even when their words differ."""
    return {m.group(0).lower() for m in _SYMPTOM.finditer(text) if len(m.group(0).strip("-")) > 1}


def term_weights(finding: dict, cap: int = MAX_TERMS) -> dict:
    """Up to `cap` single-word queries with their weight: the title's code names and words
    (three each, weight 1), then the evidence's code names (two) and file stems (one) at half
    — what the evidence cites is where the defect lives, not what it is."""
    title = str(finding.get("title") or "")
    evidence = [str(e) for e in finding.get("evidence") or [] if isinstance(e, str)]
    picks: dict = {}

    def take(items, n, weight):
        for item in items:
            if len(picks) >= cap or n <= 0:
                return
            if item.lower() not in {p.lower() for p in picks}:
                picks[item] = weight
                n -= 1

    take(_code_names(title), 3, TITLE_WEIGHT)
    take(_title_words(title), 3, TITLE_WEIGHT)
    take(_code_names(" ".join(evidence)), 2, EVIDENCE_WEIGHT)
    take(_stems(evidence), 1, EVIDENCE_WEIGHT)
    return picks


def terms_of(finding: dict, cap: int = MAX_TERMS) -> list[str]:
    return list(term_weights(finding, cap))


def remote_of(profile_text: str, repo: Path | None) -> str | None:
    """`owner/name` from the profile's Repo-Remote, else the checkout's origin."""
    m = re.search(r"^\*{0,2}Repo-Remote:\*{0,2}\s*`?([^`\n]+?)`?\s*$", profile_text, re.M)
    url = m.group(1).strip() if m else ""
    if not url and repo is not None:
        proc = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                              capture_output=True, text=True)
        url = proc.stdout.strip() if proc.returncode == 0 else ""
    hit = _REMOTE.search(url)
    return f"{hit.group(1)}/{hit.group(2)}" if hit else None


def search(remote: str, term: str, limit: int = LIMIT) -> tuple[list[dict], str]:
    """One `gh search issues` query: (items, problem)."""
    cmd = ["gh", "search", "issues", "--repo", remote, "--include-prs", "--limit", str(limit),
           "--json", "number,title,state,url,isPullRequest,updatedAt", term]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"gh could not run: {str(exc)[:120]}"
    if proc.returncode != 0:
        return [], (proc.stderr or proc.stdout).strip().splitlines()[-1][:160] if (proc.stderr or proc.stdout).strip() else f"gh exit {proc.returncode}"
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return [], "gh returned something other than JSON"
    return [r for r in rows if isinstance(r, dict) and r.get("number")], ""


def rank(hits_by_term: dict, title: str, keep: int = KEEP, weights: dict | None = None) -> list[dict]:
    """Items ranked by the weight of the terms that returned them, a number or special value
    the two titles share, then plain title overlap."""
    words = set(_title_words(title))
    symptoms = _symptoms(title)
    weights = weights or {}
    items: dict = {}
    for term, rows in hits_by_term.items():
        for r in rows:
            it = items.setdefault(int(r["number"]), {
                "number": int(r["number"]), "title": str(r.get("title") or ""),
                "state": str(r.get("state") or "").lower(),
                "kind": "pr" if r.get("isPullRequest") else "issue",
                "url": str(r.get("url") or ""), "updated": str(r.get("updatedAt") or "")[:10],
                "hits": []})
            if term not in it["hits"]:
                it["hits"].append(term)
    for it in items.values():
        overlap = len(words & set(_title_words(it["title"])))
        shared = sorted(symptoms & _symptoms(it["title"]))
        it["overlap"] = overlap
        if shared:
            it["symptoms"] = shared
        it["score"] = round(sum(weights.get(t, 1.0) for t in it["hits"])
                            + SYMPTOM_WEIGHT * len(shared) + overlap / 4, 3)
    ranked = sorted(items.values(), key=lambda it: (-it["score"], it["number"]))
    return ranked[:keep]


def load_related(qa_root) -> dict:
    """The latest related-items row per finding id, from `related.jsonl`; {} when none."""
    latest: dict = {}
    try:
        lines = (Path(qa_root) / RELATED_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return latest
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            latest[str(row["id"])] = row
    return latest


def describe(item: dict) -> str:
    return f"#{item['number']} {item.get('state', '?')} {'PR' if item.get('kind') == 'pr' else 'issue'}"


def main(argv=None, _search=search, _sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(prog="verdict-dupes", description=__doc__.split("\n\n")[0])
    ap.add_argument("project", help="project key or a repo path whose .qa/ holds state.json")
    ap.add_argument("ids", nargs="*", help="finding ids to search (default: every open Major+ finding)")
    ap.add_argument("--remote", help="owner/name of the GitHub repository (default: the profile's "
                                     "Repo-Remote, else the checkout's origin)")
    ap.add_argument("--show", action="store_true", help="print each finding's query terms; search nothing")
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-dupes: {err['error']}", file=sys.stderr)
        return 2
    qa_root = Path(state["_qa_root"])
    wanted = set(args.ids)
    findings = [f for f in state.get("findings") or []
                if (str(f.get("id")) in wanted if wanted else wants_search(f))]
    if not findings:
        print("verdict-dupes: nothing to search", file=sys.stderr)
        return 2
    if args.show:
        for f in findings:
            print(f"{f.get('id')}  {' · '.join(terms_of(f)) or '(no terms)'}")
        return 0
    try:
        profile_text = (qa_root / "profile.md").read_text(encoding="utf-8")
    except OSError:
        profile_text = ""
    remote = args.remote or remote_of(profile_text, repo_for_root(qa_root))
    if not remote:
        print("verdict-dupes: no GitHub remote — set Repo-Remote in profile.md or pass --remote owner/name",
              file=sys.stderr)
        return 2
    if _search is search and shutil.which("gh") is None:
        print("verdict-dupes: `gh` is not installed — the tracker search runs through it", file=sys.stderr)
        return 2
    rows, first = [], True
    for f in findings:
        weights = term_weights(f)
        terms = list(weights)
        hits, problem = {}, ""
        for term in terms:
            if not first:
                _sleep(PAUSE_S)
            first = False
            items, problem = _search(remote, term)
            if problem:
                break
            hits[term] = items
        ranked = rank(hits, str(f.get("title") or ""), weights=weights) if hits else []
        row = {"id": str(f.get("id")), "at": clock.stamp(), "remote": remote,
               "run_number": state.get("run_number"), "queries": list(hits), "items": ranked}
        if problem:
            row["problem"] = problem
        rows.append(row)
        lead = ranked[0] if ranked else None
        print(f"verdict-dupes: {row['id']} — "
              + (f"{describe(lead)} “{lead['title'][:70]}” (hits: {', '.join(lead['hits'])})"
                 + (f"; {len(ranked) - 1} more" if len(ranked) > 1 else "")
                 if lead else "nothing related")
              + (f" · search stopped: {problem}" if problem else ""), file=sys.stderr)
        if problem and not hits:
            break
    searched = [r for r in rows if r["queries"]]
    with (qa_root / RELATED_FILE).open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"verdict-dupes: {len(searched)} of {len(findings)} finding(s) searched in {remote} · "
          f"{sum(1 for r in searched if r['items'])} with related items · "
          f"{sum(1 for r in searched if any(i['kind'] == 'pr' and i['state'] == 'open' for i in r['items']))} "
          f"with an open PR among them → {qa_root / RELATED_FILE}", file=sys.stderr)
    return 0 if searched else 2


if __name__ == "__main__":
    sys.exit(main())
