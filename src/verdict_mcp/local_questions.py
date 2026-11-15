"""The questions: the contract and classify prompts for each way of reading code, the
examination of one chunk, and a finding built from an answer under the ceilings.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from . import languages
    from .local_model import Model
    from .local_chunks import Chunk
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import languages
    from local_model import Model
    from local_chunks import Chunk


# ── the questions ─────────────────────────────────────────────────────────────


CONTRACT_Q = """You are a software tester reading one function. Its docstring, or the name
and the code, state what it must do.

File: {path}
```python
{source}
```

Does the code do exactly what it claims? Look for: a boundary that is off by one (`>` where
`>=` is meant), a rounding or conversion that loses value, an error path that is swallowed,
a condition that can never be true, a value returned unrounded or unvalidated.

Reply with JSON only:
{{"verdict": "matches" or "mismatch",
  "line": <the line number from the left margin above, or null>,
  "mechanism": "<one sentence: what the code does, and what it should do instead>"}}"""


CLASSIFY_Q = """You are a software tester. A defect has been claimed in this function.

File: {path}
```python
{source}
```

Claim: {mechanism}

Answer with JSON only:
{{"is_real": true or false,
  "severity": "Blocker" or "Critical" or "Major" or "Minor" or "Trivial",
  "title": "<one sentence naming the defect and its consequence, under 120 characters>",
  "impact": "<one sentence: what a caller gets wrong because of it>"}}"""


# The same two questions for a function in any other language. The Python wording above is kept
# word for word: the evals that measured it would otherwise be measuring something else.
BRACES_CONTRACT_Q = """You are a software tester reading one {language} function from a larger
codebase. Its doc comment, or its name and the code, state what it must do.

File: {path}{context}
```{fence}
{source}
```

Does the code do exactly what it claims? Look for: a boundary that is off by one (`>` where
`>=` is meant), a condition that can never be true or is always true, an error or a failed
result that is swallowed, a null or undefined value used without a check, an async call whose
result is never awaited, a conversion or rounding that loses value, state changed in the wrong
order or left half-written when a step fails.

Judge only what this code shows. A check its callers make, or one an attribute, a filter or a
middleware enforces, is not visible here: do not report a missing check unless this code is
where outside input enters and nothing shown performs it.{note}

Reply with JSON only:
{{"verdict": "matches" or "mismatch",
  "line": <the line number from the left margin above, or null>,
  "mechanism": "<one sentence: what the code does, and what it should do instead>"}}"""


BRACES_CLASSIFY_Q = """You are a software tester. A defect has been claimed in this {language} function.

File: {path}{context}
```{fence}
{source}
```

Claim: {mechanism}

Answer with JSON only:
{{"is_real": true or false,
  "severity": "Blocker" or "Critical" or "Major" or "Minor" or "Trivial",
  "title": "<one sentence naming the defect and its consequence, under 120 characters>",
  "impact": "<one sentence: what a caller gets wrong because of it>"}}"""


# A language read without function boundaries — SQL, shell, Perl and the rest — is shown as the
# lines around a change, and the question says so: a model told it holds a whole function reports
# what it was not shown as missing.
LINES_CONTRACT_Q = """You are a software tester reading an excerpt of {language} from a larger
codebase: the lines around a change, not a whole function. Its comments and its code state what
it must do.

File: {path}{context}
```{fence}
{source}
```

Does the code do exactly what it claims? Look for: a boundary that is off by one, a condition
that can never be true or is always true, an error or a failed command that is ignored, a value
used before it is checked, quoting or escaping that lets input run as code, state changed in the
wrong order or left half-written when a step fails.

Judge only what these lines show. Code above or below the excerpt is not visible: do not report
something as missing unless these lines are where it must happen and nothing shown does it.{note}

Reply with JSON only:
{{"verdict": "matches" or "mismatch",
  "line": <the line number from the left margin above, or null>,
  "mechanism": "<one sentence: what the code does, and what it should do instead>"}}"""


# A template is markup with code in its tags. What goes wrong there is what a page shows, to whom,
# and how: the defects a template holds are not the ones a function holds.
TEMPLATE_CONTRACT_Q = """You are a software tester reading an excerpt of a {language} from a
website: markup with code in its tags. The code that renders it and the routes that serve it are
not shown.

File: {path}{context}
```{fence}
{source}
```

Does the template do what it claims? Look for: a condition that shows or hides the wrong thing
(one role's content shown to another), a value printed without escaping where it can come from a
user (`v-html`, `{{@html}}`, `|safe`, `{{!! !!}}`, `raw`, `<%==`, `dangerouslySetInnerHTML`), a form
that posts somewhere wrong or without the framework's CSRF token, a field that browsers autofill
hidden as a trap, a link or a binding to the wrong value, a branch that can never render.

Judge only what these lines show: a check made where the page is rendered is not visible here.{note}

Reply with JSON only:
{{"verdict": "matches" or "mismatch",
  "line": <the line number from the left margin above, or null>,
  "mechanism": "<one sentence: what the template does, and what it should do instead>"}}"""


EXCERPT_CLASSIFY_Q = """You are a software tester. A defect has been claimed in these lines of {language}.

File: {path}{context}
```{fence}
{source}
```

Claim: {mechanism}

Answer with JSON only:
{{"is_real": true or false,
  "severity": "Blocker" or "Critical" or "Major" or "Minor" or "Trivial",
  "title": "<one sentence naming the defect and its consequence, under 120 characters>",
  "impact": "<one sentence: what a caller gets wrong because of it>"}}"""


def contract_question(chunk: Chunk) -> str:
    """The first question about `chunk`, worded for its language and for what its lines are."""
    if chunk.lang == "python":
        return CONTRACT_Q.format(path=chunk.path, source=chunk.numbered())
    unit = getattr(chunk, "unit", "function")
    if unit == "template":
        return TEMPLATE_CONTRACT_Q.format(**_brace_fields(chunk))
    if unit == "excerpt":
        return LINES_CONTRACT_Q.format(**_brace_fields(chunk))
    return BRACES_CONTRACT_Q.format(**_brace_fields(chunk))


def classify_question(chunk: Chunk, mechanism: str) -> str:
    """The second question about `chunk`: is the claimed defect real, and how bad."""
    if chunk.lang == "python":
        return CLASSIFY_Q.format(path=chunk.path, source=chunk.numbered(), mechanism=mechanism)
    if getattr(chunk, "unit", "function") in ("excerpt", "template"):
        return EXCERPT_CLASSIFY_Q.format(mechanism=mechanism, **_brace_fields(chunk))
    return BRACES_CLASSIFY_Q.format(mechanism=mechanism, **_brace_fields(chunk))


def _brace_fields(chunk: Chunk) -> dict:
    language = languages.name_of(chunk.lang)
    if getattr(chunk, "unit", "function") == "template" and not language.endswith("template"):
        language += " template"                 # a Vue component's template, a Razor view's markup
    return {"language": language, "fence": languages.fence_of(chunk.lang) or chunk.lang,
            "path": chunk.path, "source": chunk.numbered(),
            "context": f"\nIt is declared inside: {chunk.context}" if chunk.context else "",
            "note": f"\n{chunk.note}" if getattr(chunk, "note", "") else ""}


def examine(model: Model, chunk: Chunk, hint: str | None = None) -> dict | None:
    """Two bounded calls: is it wrong, and if so how bad. Neither sees the other's
    context — the second is given the claim as text, not as history. `hint` is what the
    assertion-gap census measured about this function, appended to the first question."""
    first = model.ask_json(contract_question(chunk) + (f"\n\n{hint}" if hint else ""))
    if not first or str(first.get("verdict")) != "mismatch":
        return None
    mechanism = str(first.get("mechanism") or "").strip()
    if len(mechanism) < 12:
        return None
    line = first.get("line")
    line = int(line) if isinstance(line, (int, float)) and chunk.start <= line <= chunk.end \
        else chunk.start
    second = model.ask_json(classify_question(chunk, mechanism), max_tokens=600)
    if not second or second.get("is_real") is not True:
        return None
    severity = str(second.get("severity") or "Minor")
    if severity not in ("Blocker", "Critical", "Major", "Minor", "Trivial"):
        severity = "Minor"
    title = str(second.get("title") or "").strip() or f"{chunk.name}: {mechanism[:100]}"
    return {"function": chunk.name, "path": chunk.path, "line": line, "severity": severity,
            "title": title[:200], "mechanism": mechanism,
            "impact": str(second.get("impact") or "").strip()}


UNPROVEN_CEILING = "Minor"


def capped(severity: str, proven: bool) -> str:
    """A claim nobody executed cannot outrank one that was executed.

    Measured on boltons, a real 30-module library: the local model filed 35 findings from
    reading alone, every one of them `REAL_DEFECT`, 34 of them Major or above, across
    three modules. A tester whose every finding is Critical has no severity at all, and a
    reader learns to skip the list. So severity from reading is capped until a
    counterfactual moves it: prove the line and the model's own severity stands, leave it
    unproven and it sits below everything the suite actually demonstrated.
    """
    return severity if proven else UNPROVEN_CEILING


# A failing test is measured; what the model says it means is not. Its severity is held at
# Major until a counterfactual proves the line — above a reading nobody executed, below
# anything that would block a release on a guess. Measured 2026-10-14, the local tier on a
# 120B model over the pricer baseline fixture: one run in three filed the stale 12 % fee
# expectation as a `Blocker` from the failure text alone, and every filed `Blocker` joins
# `release_blockers`, where it stays until something resolves it.
FAILURE_CEILING = "Major"


_SEVERITY_RANK = {"Trivial": 0, "Minor": 1, "Major": 2, "Critical": 3, "Blocker": 4}


def capped_failure(severity: str) -> str:
    """The model's severity for a failing test, never above `FAILURE_CEILING`."""
    rank = _SEVERITY_RANK.get(str(severity))
    if rank is None or rank > _SEVERITY_RANK[FAILURE_CEILING]:
        return FAILURE_CEILING
    return str(severity)


def finding_of(claim: dict, ident: str, chunk_source: str, proof: dict | None = None) -> dict:
    """A claim becomes a finding file — `confidence: hypothesis` unless `proof` is a
    counterfactual that ran: the cited line changed in a scratch copy, the expression
    re-run, and the value followed the line. A model's reading alone is never `proven`;
    a small-model run that claimed it would be exactly the flattery this project exists
    to reject. (Until 0.90.9 this said every finding here was a hypothesis, which stopped
    being true when probes arrived, and a 120B reader filed the stale sentence as a
    Critical defect in the 0.90.9 release gate.)"""
    excerpt = "\n".join(chunk_source.splitlines()[:6])
    proven = bool(proof and proof.get("status") == "proven")
    evidence = [
        f"{claim['path']}:{claim['line']} — read against the function's own contract"
        + ("" if proven else "; not executed, not counterfactually tested"),
        f"excerpt:\n{excerpt}",
    ]
    if proven:
        evidence.insert(0, (
            f"COUNTERFACTUAL (both runs in the scratch copy at "
            f"{proof.get('scratch') or 'a temporary directory'}, PYTHONDONTWRITEBYTECODE=1, "
            f"__pycache__ swept, import verified inside the scratch, environment "
            f"allowlisted): `{proof['expression']}` returns {proof['before']!r} at HEAD; with "
            f"{claim['path']}:{proof['line']} changed from `{proof['was']}` to "
            f"`{proof['now']}` it returns {proof['after']!r}. {proof['reason']}."))
    elif proof:
        # A probe that was refused or could not run is on the record beside the claim it
        # failed to prove — what was asked to run, where, and why it did not (audit
        # 2026-10-02, O-S-1 (5)). The citation stays the first line.
        text = f"`{proof['expression']}`" if proof.get("expression") else "(no expression)"
        evidence.append(
            f"PROBE {text} — {proof.get('status')}: {proof.get('reason')}; "
            + (f"ran in {proof['scratch']}" if proof.get("scratch") else "nothing ran"))
    narrative = f"{claim['mechanism']} {claim['impact']}".strip()
    narrative += (" Proven by counterfactual, not by reading: the value follows the line."
                  if proven else
                  f" Filed by `verdict-local` from a bounded reading of this function "
                  f"alone, with no execution behind it — so its severity is held at "
                  f"{UNPROVEN_CEILING} however bad it reads. Confirm before acting.")
    return {
        "id": ident,
        "title": claim["title"],
        "severity": capped(claim["severity"], proven),
        "priority": "P1" if proven and claim["severity"] not in ("Minor", "Trivial") else "P2",
        "status": "open",
        "failure_classification": "REAL_DEFECT",
        "confidence": "proven" if proven else "hypothesis",
        "evidence": evidence,
        "root_cause": {"mechanism": claim["mechanism"],
                       "origin": "not investigated in local mode"},
        "narrative": narrative,
    }
