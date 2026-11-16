"""Items, identity and scrubbing: the finding a check files, its fingerprint, whether a value
looks live, and the redaction that runs before anything leaves.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import sys
from pathlib import Path

try:
    from .hygiene_patterns import (_JWT, _PLACEHOLDER, _SCRUBBED, _SCRUB_BASE64, _SCRUB_RUN,
                                   _SEQUENTIAL, _URL_CREDENTIALS)
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_patterns import (_JWT, _PLACEHOLDER, _SCRUBBED, _SCRUB_BASE64, _SCRUB_RUN,
                                  _SEQUENTIAL, _URL_CREDENTIALS)


# ── items, identity, scrubbing ────────────────────────────────────────────
def _scrub(s: str) -> str:
    """Every credential-shaped run replaced by what it is, live-looking or not: a
    provider key by its name, a JWT, a URL's password, and a long run that looks
    random. An excerpt is for recognising the line, never for reading the value; a
    digit-free, word-like token is the one shape no rule can tell from prose."""
    for name, rx in _SCRUBBED:
        s = rx.sub(f"<{name}>", s)
    s = _JWT.sub("<jwt>", s)
    s = _URL_CREDENTIALS.sub(r"\1<redacted>@", s)
    s = _SCRUB_RUN.sub(_scrub_run, s)
    return _SCRUB_BASE64.sub(_scrub_base64, s)


def _scrub_run(m) -> str:
    run = m.group(0)
    digits = sum(c.isdigit() for c in run)
    letters = sum(c.isalpha() for c in run)
    return "<redacted>" if digits >= 3 and letters >= 3 and _entropy(run[-32:]) >= 3.3 else run


def _scrub_base64(m) -> str:
    run = m.group(0)
    upper = sum(c.isupper() for c in run)
    lower = sum(c.islower() for c in run)
    digits = sum(c.isdigit() for c in run)
    return "<redacted>" if upper >= 3 and lower >= 3 and digits >= 2 and _entropy(run) >= 4.2 else run


def _item(kind, tier, rel, line, text, why, *, redacted=None, key=None):
    # A caller that hands over `redacted` built the excerpt and the reason from
    # names, paths and counts, never from the line: scrubbing them again only
    # turns a timestamped migration path into "<redacted>". Where a reason does
    # carry text from the file (the comment above a lead), it is scrubbed as it
    # is built.
    if redacted is None:
        text, why = _scrub(text), _scrub(why)
    shown = redacted if redacted is not None else text.strip()[:120]
    return {"kind": kind, "tier": tier, "path": rel, "line": line, "excerpt": shown, "why": why,
            "_key": key if key is not None else (redacted if redacted is not None
                                                 else " ".join(text.split()))}


def _fingerprint(items: list) -> list:
    seen: dict = {}
    for it in items:
        base = (it["kind"], it["path"], it.pop("_key"))
        n = seen.get(base, 0)
        seen[base] = n + 1
        it["fingerprint"] = hashlib.sha1("\0".join((*base, str(n))).encode("utf-8")).hexdigest()[:16]
    return items


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    return -sum(s.count(c) / len(s) * math.log2(s.count(c) / len(s)) for c in set(s))


def _looks_live(token: str) -> bool:
    low = token.lower()
    if _PLACEHOLDER.search(low) or any(seq in low for seq in _SEQUENTIAL):
        return False
    if not (re.search(r"[0-9]", low) and re.search(r"[a-z]", low)):
        return False            # all letters or all digits: a word-like match, not a credential
    tail = low[-24:]
    return len(tail) < 16 or _entropy(tail) >= 3.0


def _jwt_claims(middle: str) -> dict | None:
    """A JWT's claims, or None. A payload past 4 KB is no key anyone copied from a
    dashboard, and a payload nested past what the decoder holds must not cost the
    scan."""
    if len(middle) > 4096:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(middle + "=" * (-len(middle) % 4)))
    except Exception:
        return None
    return claims if isinstance(claims, dict) else None


def _redact(name: str, token: str) -> str:
    return f"{name}: <{len(token)} chars, ends …{token[-4:]}>"
