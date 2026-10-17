"""Where to read first — the changed code no test executes, money and auth paths first.

facts.json has carried the coverage of every changed line (`coverage.per_file`) and a map of
modules by coverage (`reading_map`) since 0.86.0, and the tester's prompt never pointed at
either: each run re-derived where to look. Measured 2026-10-17 on two stranger baselines: on
one, the top-ranked never-entered function sat in the file holding half of the known defects;
on the other, the known defect sat in code the suite executes without asserting the case,
which line coverage cannot rank. So this is where to start, not where to stop. Per changed
function,
how many of its changed lines no test executed, the ones on a money or auth path first; on
a run with a range but no coverage, the changed functions by size; on a baseline, the least
covered modules, risk paths first. A ranking, never a finding and never a gate.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

CAP = 15
# Word stems that put a function or a file on a money or auth path. A whole word, or a
# word that begins with a stem of four letters or more: `rate` matches `rate` and `rates`,
# never `generate`; `refund` matches `refunded`.
RISK_STEMS = (
    "pay", "payment", "payout", "price", "pricing", "refund", "charge", "invoice", "order",
    "cart", "checkout", "discount", "voucher", "offer", "benefit", "coupon", "tax", "fee",
    "balance", "ledger", "money", "amount", "total", "currency", "rate", "rates", "interest",
    "loan", "wallet", "capture", "settle", "auth", "login", "token", "session", "password",
    "permission", "crypt", "signature", "verify", "credential",
)


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def risk_of(path: str, function: str = "", globs=None) -> str:
    """Why this path or function is a risk path ('' when it is not): the profile's
    `risk_paths` glob that matched, or the stem a word of its name begins with."""
    if globs:
        for glob in globs:
            if fnmatch.fnmatch(path, glob):
                return f"risk_paths: {glob}"
        return ""
    for word in _words(path) + _words(function):
        for stem in RISK_STEMS:
            if word == stem or (len(stem) >= 4 and word.startswith(stem)):
                return stem
    return ""


def enclosing(repo: Path, rel: str, lines) -> dict:
    """`{qualified function name: [lines]}` — each line under the innermost function that
    contains it, `(module)` for the rest. An unparseable file puts every line at module level."""
    out: dict = {}
    try:
        tree = ast.parse((Path(repo) / rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return {"(module)": sorted(lines)}
    spans = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    spans.append((child.lineno, getattr(child, "end_lineno", child.lineno), name))
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    for line in sorted(lines):
        inside = [s for s in spans if s[0] <= line <= s[1]]
        name = max(inside, key=lambda s: s[0])[2] if inside else "(module)"
        out.setdefault(name, []).append(line)
    return out


def _expand(ranges) -> set:
    out = set()
    for span in ranges or []:
        if isinstance(span, (list, tuple)) and len(span) == 2:
            out |= set(range(int(span[0]), int(span[1]) + 1))
        elif isinstance(span, int):
            out.add(span)
    return out


def _gap_items(gaps: dict | None) -> list[dict]:
    """Assertion-gap survivors as ranked items: a line the listed tests execute and do not check."""
    out, seen = [], set()
    for g in (gaps or {}).get("survived") or []:
        if (g["path"], g["function"]) in seen:          # one item per function: its first survivor
            continue
        seen.add((g["path"], g["function"]))
        out.append({"path": g["path"], "function": g["function"], "lines": str(g["line"]),
                    "risk": g.get("risk") or "",
                    "gap": (f"`{g['before']}` -> `{g['after']}` ({g['operator']}) leaves "
                            f"{len(g.get('tests') or [])} test(s) that run this line green")})
    return out


def read_first(repo: Path, coverage: dict | None, reading_map: dict | None, changed=None,
               globs=None, is_test=lambda p: False, cap: int = CAP, gaps: dict | None = None) -> dict | None:
    """The ranking, or None when there is nothing to rank. Assertion-gap survivors, when a
    census ran, come first: they are concrete lines the suite executes without checking."""
    ranked = _read_first(repo, coverage, reading_map, changed, globs, is_test, cap)
    gap_items = _gap_items(gaps)
    if not gap_items:
        return ranked
    seen = {(i["path"], i["function"]) for i in gap_items}
    rest = [i for i in (ranked or {}).get("items") or [] if (i["path"], i.get("function")) not in seen]
    basis = "assertion gaps first (a mutant the tests that run the line leave green), then " + \
        ((ranked or {}).get("basis") or "nothing else ranked")
    items = (gap_items + rest)[:cap]
    return {"basis": basis, "items": items, "of": len(gap_items) + (ranked or {}).get("of", 0),
            "risk_from": (ranked or {}).get("risk_from") or ("profile risk_paths" if globs else "name stems")}


def _read_first(repo: Path, coverage: dict | None, reading_map: dict | None, changed=None,
                globs=None, is_test=lambda p: False, cap: int = CAP) -> dict | None:
    cov = coverage if isinstance(coverage, dict) else {}
    items = []
    if cov.get("status") == "measured" and cov.get("per_file"):
        basis = "changed lines no test executes, risk paths first"
        for path, entry in cov["per_file"].items():
            path = str(path).replace("\\", "/")
            if is_test(path) or not isinstance(entry, dict):
                continue
            lines = _expand(entry.get("unexercised_ranges"))
            for name, hit in enclosing(repo, path, lines).items() if lines else ():
                items.append({"path": path, "function": name, "unexercised_changed_lines": len(hit),
                              "lines": f"{hit[0]}-{hit[-1]}" if len(hit) > 1 else str(hit[0]),
                              "risk": risk_of(path, name, globs)})
        items.sort(key=lambda i: (not i["risk"], -i["unexercised_changed_lines"], i["path"], i["function"]))
    elif changed:
        basis = "changed lines (coverage not measured: whether a test executes them is unknown), risk paths first"
        for path, lines in changed.items():
            path = str(path).replace("\\", "/")
            if is_test(path):
                continue
            for name, hit in enclosing(repo, path, lines).items():
                items.append({"path": path, "function": name, "changed_lines": len(hit),
                              "lines": f"{hit[0]}-{hit[-1]}" if len(hit) > 1 else str(hit[0]),
                              "risk": risk_of(path, name, globs)})
        items.sort(key=lambda i: (not i["risk"], -i["changed_lines"], i["path"], i["function"]))
    elif isinstance(reading_map, dict) and reading_map.get("functions_never_entered"):
        basis = "no range: functions no test ever entered, risk paths first"
        for u in reading_map["functions_never_entered"]:
            items.append({"path": u["path"], "function": u["function"], "missed_lines": u["missed"],
                          "risk": risk_of(u["path"], u["function"], globs)})
        items.sort(key=lambda i: (not i["risk"], -i["missed_lines"], i["path"], i["function"]))
    elif isinstance(reading_map, dict) and reading_map.get("lowest"):
        basis = "no range: the least covered modules, risk paths first"
        for m in reading_map["lowest"]:
            items.append({"path": m["path"], "percent": m.get("percent"),
                          "open_findings": m.get("open_findings", 0), "risk": risk_of(m["path"], "", globs)})
        items.sort(key=lambda i: (not i["risk"], i["percent"] if i["percent"] is not None else 101, i["path"]))
    else:
        return None
    if not items:
        return None
    return {"basis": basis, "items": items[:cap], "of": len(items),
            "risk_from": "profile risk_paths" if globs else "name stems (set risk_paths in the profile to choose)"}
