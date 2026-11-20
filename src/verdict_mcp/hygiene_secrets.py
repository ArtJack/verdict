"""Tier 1, secrets: keys and tokens in code, secret files and env files, public env vars that
carry a secret, and the Google keys and sites they open.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

try:
    from .hygiene_const import CODE_SUFFIXES, SERVICE_ACCOUNT_MAX, _CODE_CLASS
    from .hygiene_patterns import (_BASE64_LINE, _CLIENT_PREFIXES, _CONFIG_TOKENS, _C_TOKENS,
                                   _ENV_ASSIGN, _ENV_FILE, _ENV_TEMPLATE, _GOOGLE_KEY, _GOOGLE_WHY,
                                   _HASH_COMMENTED, _HASH_COMMENTED_NAMES, _HASH_TOKENS,
                                   _HCL_SUFFIXES, _HCL_TOKENS, _INLINE_KEY, _JWT, _KEY_CONTAINER,
                                   _KEY_QUALIFIERS, _KEY_WORDS, _NOT_A_SECRET_TAIL, _PRIVATE_KEY,
                                   _PUBLIC_ENV_SECRET, _PUBLIC_VALUES, _PUBLIC_WORDS,
                                   _SECRET_PATTERNS, _SECRET_WORDS, _SERVICE_ACCOUNT,
                                   _SERVICE_ACCOUNT_KEY, _TEMPLATE_END, _TRIPLE_QUOTED)
    from .hygiene_paths import _is_script_path, is_test_path
    from .hygiene_git import _lines
    from .hygiene_scrub import _item, _jwt_claims, _looks_live, _redact
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import CODE_SUFFIXES, SERVICE_ACCOUNT_MAX, _CODE_CLASS
    from hygiene_patterns import (_BASE64_LINE, _CLIENT_PREFIXES, _CONFIG_TOKENS, _C_TOKENS,
                                  _ENV_ASSIGN, _ENV_FILE, _ENV_TEMPLATE, _GOOGLE_KEY, _GOOGLE_WHY,
                                  _HASH_COMMENTED, _HASH_COMMENTED_NAMES, _HASH_TOKENS,
                                  _HCL_SUFFIXES, _HCL_TOKENS, _INLINE_KEY, _JWT, _KEY_CONTAINER,
                                  _KEY_QUALIFIERS, _KEY_WORDS, _NOT_A_SECRET_TAIL, _PRIVATE_KEY,
                                  _PUBLIC_ENV_SECRET, _PUBLIC_VALUES, _PUBLIC_WORDS,
                                  _SECRET_PATTERNS, _SECRET_WORDS, _SERVICE_ACCOUNT,
                                  _SERVICE_ACCOUNT_KEY, _TEMPLATE_END, _TRIPLE_QUOTED)
    from hygiene_paths import _is_script_path, is_test_path
    from hygiene_git import _lines
    from hygiene_scrub import _item, _jwt_claims, _looks_live, _redact


# ── tier 1 ────────────────────────────────────────────────────────────────
def _secrets(rel, lines):
    out = []
    for i, line in enumerate(lines, 1):
        for name, rx in _SECRET_PATTERNS:
            for m in rx.finditer(line):
                if _looks_live(m.group(0)):
                    out.append(_item("secret_in_code", 1, rel, i, line,
                                     f"a {name} in the source: anyone who can read the repository can use it",
                                     redacted=_redact(name, m.group(0))))
        for m in _JWT.finditer(line):
            if _service_role(m.group(1)):
                out.append(_item("secret_in_code", 1, rel, i, line,
                                 "a Supabase service_role key: it bypasses row-level security",
                                 redacted=_redact("supabase service_role key", m.group(0))))
        if _PRIVATE_KEY.search(line):
            nxt = next((ln.strip() for ln in lines[i:i + 3] if ln.strip()), "")
            if _BASE64_LINE.match(nxt):
                out.append(_item("secret_in_code", 1, rel, i, line, "a private key in the source",
                                 redacted="private key block"))
    return out


def _service_role(middle: str) -> bool:
    """A service_role JWT — except the one the Supabase CLI publishes for local
    development (`"iss": "supabase-demo"`), which every such project carries."""
    claims = _jwt_claims(middle)
    return (claims is not None and claims.get("role") == "service_role"
            and claims.get("iss") != "supabase-demo")


def _google_sites(rel, lines):
    """Every Google API key in one file, as (digest, path, line, excerpt). The value
    goes no further than this: the digest tells two keys apart, the excerpt is the
    redacted form."""
    return [(hashlib.sha1(m.group(0).encode("utf-8")).hexdigest(), rel, i,
             _redact(_GOOGLE_KEY[0], m.group(0)))
            for i, line in enumerate(lines, 1) for m in _GOOGLE_KEY[1].finditer(line)]


def _google_keys(sites):
    """One lead per distinct key and platform across the repository, at its first
    site in (path, line) order: a Maps key pasted into every page template is one
    thing to check, not fifty."""
    out, seen = [], set()
    for digest, rel, line, shown in sorted(sites, key=lambda s: (s[1], s[2])):
        key = (digest, _key_platform(rel))
        if key not in seen:
            seen.add(key)
            out.append(_item("google_api_key", 3, rel, line, "", _GOOGLE_WHY, redacted=shown))
    return out


def _key_platform(rel: str) -> str:
    """Which application restriction a Google key found here needs. A key carries
    one kind — websites, Android apps, iOS apps or IP addresses — so the same key
    in an Android build and on a web page is two things to check, not one. Only the
    Firebase configs and an android/ or ios/ directory say which; the rest is one
    bucket, the web and whatever else."""
    parts = rel.lower().split("/")
    if parts[-1] == "google-services.json" or "android" in parts[:-1]:
        return "android"
    if parts[-1] == "googleservice-info.plist" or "ios" in parts[:-1]:
        return "ios"
    return "web"


def _secret_file_kind(rel: str, name: str, size: int):
    """Which committed-secret-file check a path gets, decided by its name and its
    size in the tree, before anything is read: "env", "container", "pem", "json"
    or None. These checks run past the file cap, so a JSON file is a candidate
    service-account key only while it is small enough to be one."""
    low = name.lower()
    # Android and React Native templates commit debug.keystore on purpose, and a
    # mkcert certificate for localhost guards nothing.
    if is_test_path(rel) or name == "debug.keystore":
        return None
    if _ENV_FILE.search(rel) and not _ENV_TEMPLATE.search(name):
        return "env"
    if _KEY_CONTAINER.search(name):
        return "container"
    if low.endswith((".pem", ".key")):
        return None if "localhost" in low else "pem"
    return "json" if low.endswith(".json") and size <= SERVICE_ACCOUNT_MAX else None


def _secret_file(kind, rel, name, text, lines, found):
    items = found["items"]
    if kind == "container":
        items.append(_item("secret_file_tracked", 1, rel, 1, name, "a key file is committed",
                           redacted=f"{name} committed"))
    elif text is None:
        return                  # binary (git-crypt, a Keynote .key) or too large to read
    elif kind == "env":
        _env_file(rel, name, lines, found)
    elif kind == "pem" and _private_key_block(lines):
        items.append(_item("secret_file_tracked", 1, rel, 1, name, "a private key file is committed",
                           redacted=f"{name} committed"))
    elif kind == "json" and _service_account_key(text):
        items.append(_item("secret_file_tracked", 1, rel, 1, name,
                           "a cloud service-account key is committed", redacted=f"{name} committed"))


def _private_key_block(lines) -> bool:
    """A BEGIN PRIVATE KEY line whose next non-empty line is key material — not a
    template with `...` where the key goes."""
    for i, line in enumerate(lines):
        if _PRIVATE_KEY.search(line):
            nxt = next((ln.strip() for ln in lines[i + 1:] if ln.strip()), "")
            if _BASE64_LINE.match(nxt):
                return True
    return False


def _service_account_key(text: str) -> bool:
    return ('"service_account"' in text and _SERVICE_ACCOUNT.search(text) is not None
            and _SERVICE_ACCOUNT_KEY.search(text) is not None)


def _env_file(rel, name, lines, found):
    """A committed env file is one finding when it holds a live secret, naming the
    variables and never their values; otherwise it is one lead. Its identity is the
    file, so adding a variable to it keeps the fingerprint."""
    live, names = _env_secrets(rel, lines)
    if not live:
        found["leads"].append(_item("env_file_committed", 3, rel, 1, name,
                                    "an environment file is committed — check that nothing in it is secret"))
        return
    listed = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    found["items"].append(_item(
        "secret_file_tracked", 1, rel, 1, name,
        "an environment file holding a live secret is committed: the value stays in the history",
        redacted=f"{name} committed" + (f", sets {listed}" if names else ""), key=""))


def _env_secrets(rel, lines):
    """Whether a committed env file holds a live secret, and the names that do.

    A line holds one when the source scan finds a provider key, a service_role JWT
    or a private key on it — or when its name is a credential's and its value
    looks like one. A value encrypted in place (SOPS `ENC[`, dotenvx `encrypted:`)
    never does. A hit on a continuation line belongs to the variable above it."""
    hits = {it["line"] for it in _secrets(rel, lines)}
    live, names, current = False, [], None
    for i, line in enumerate(lines, 1):
        body = line.strip()
        comment = body.startswith("#")
        m = _ENV_ASSIGN.match(body.lstrip("#").lstrip() if comment else body)
        if m:
            owner, value = m.group(1), _env_value(m.group(2))
            current = current if comment else owner
            if value.startswith(("ENC[", "encrypted:")):
                continue
            here = (i in hits or _INLINE_KEY.search(value) is not None
                    or (not comment and _credential_name(owner) and _env_value_live(value)))
        else:
            owner, here = (None if comment else current), i in hits
        if here:
            live = True
            if owner and owner not in names:
                names.append(owner)
    return live, names


def _env_value(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else raw[1:]
    return re.sub(r"\s+#.*$", "", raw)


def _credential_name(name: str) -> bool:
    """A name that says credential, read in order: not a setting about one
    (ACCESS_TOKEN_TTL, KEYCLOAK_URL, ADMIN_WALLET); a secret word; else a KEY or
    TOKEN, unless a public word stands right before it (MASTER_PUBLIC_KEY); an admin's
    or a master key; else a key only when no public word marks the name. A
    client-prefixed name is F9's to judge, not this one's."""
    up = name.upper()
    if up.startswith(_CLIENT_PREFIXES):
        return False
    words = up.split("_")
    if words[-1] in _NOT_A_SECRET_TAIL:
        return False
    if not _SECRET_WORDS.isdisjoint(words):
        return True
    keys = [n for n, word in enumerate(words) if word in _KEY_WORDS]
    if not keys:
        return False
    if keys[-1] > 0 and words[keys[-1] - 1] in _PUBLIC_WORDS:
        return False
    return not _KEY_QUALIFIERS.isdisjoint(words) or _PUBLIC_WORDS.isdisjoint(words)


def _env_value_live(v: str) -> bool:
    """A value that could be a credential: not empty, not a reference ($VAR, <…>, a
    path, a URL), not a sentence, not a port or a word, not a key that is public
    by design (_PUBLIC_VALUES) — and then live-looking."""
    if not v or v.startswith(("ENC[", "encrypted:", "$", "<", "/", "./", "../", "~/")):
        return False
    if v.startswith(_PUBLIC_VALUES):
        return False
    if "://" in v or re.search(r"\s", v) or len(v) < 20 or v.isdigit():
        return False
    if not (re.search(r"[0-9]", v) and re.search(r"[A-Za-z]", v)):
        return False
    return _looks_live(v)


def _public_env_sites(rel, text, lines):
    """Where a client-side variable named as a secret appears. In code the comments
    are cut first: `// never add NEXT_PUBLIC_STRIPE_SECRET_KEY` reads nothing. In
    Python a docstring is the same prose in another form, and is cut too. So are
    the comments of config, shell, Terraform, Dockerfiles and their kin: a
    workflow that says a variable must never be set there is not setting it."""
    if _PUBLIC_ENV_SECRET.search(text) is None:
        return []               # almost every file: no need to cut its comments
    suffix = Path(rel).suffix.lower()
    if suffix == ".py":
        lines = _lines(_TRIPLE_QUOTED.sub(lambda m: "\n" * m.group(0).count("\n"), "\n".join(lines)))
    if suffix in _CODE_CLASS:
        lines = _uncomment(lines, _HASH_TOKENS if suffix in (".py", ".rb") else _C_TOKENS)
    elif suffix in _HCL_SUFFIXES:
        lines = _uncomment(lines, _HCL_TOKENS)
    elif _hash_commented(rel):
        lines = _uncomment(lines, _CONFIG_TOKENS)
    return [(m.group(0), rel, i) for i, line in enumerate(lines, 1)
            for m in _PUBLIC_ENV_SECRET.finditer(line)]


def _hash_commented(rel: str) -> bool:
    """An env file (as `_eligible` admits one: `.env*`, or a `.env` suffix), config
    or shell by suffix, or a Dockerfile, Makefile, Justfile or Procfile by name."""
    name = rel.rsplit("/", 1)[-1].lower()
    return (Path(name).suffix in _HASH_COMMENTED or name in _HASH_COMMENTED_NAMES
            or name.startswith((".env", "dockerfile")))


def _app_code(rel: str) -> bool:
    return Path(rel).suffix.lower() in CODE_SUFFIXES and not _is_script_path(rel)


def _public_env(sites):
    """One item per client-side variable named as a secret, at the site where the
    bundler inlines it: app code first (a deploy script or a workflow that merely
    mentions the name comes second), then the first site in (path, line) order."""
    by_name: dict = {}
    for name, rel, line in sites:
        by_name.setdefault(name, []).append((rel, line))
    out = []
    for name, where in by_name.items():
        rel, line = min([w for w in where if _app_code(w[0])] or where)
        why = f"{name} is bundled into the client: every visitor can read it"
        if len(where) > 1:
            why += f" ({len(where)} places reference it)"
        it = _item("public_env_secret", 1, rel, line, "", why, redacted=name)
        # Its identity across runs is the variable, wherever it is read, and it is
        # gone only once every file that read it was scanned without it (reconcile).
        it["variable"] = name
        it["sites"] = sorted({r for r, _line in where})
        out.append(it)
    return out


def _uncomment(lines, tokens):
    """The lines with their comments cut out and their strings kept whole, one for
    one, so line numbers hold. A block comment stays open across lines, and so does
    a template literal: the lines inside one are text, never code, and come out
    blank like a comment's."""
    out, in_block, in_template = [], False, False
    for line in lines:
        kept, pos = [], 0
        while True:
            if in_block:
                end = line.find("*/", pos)
                if end < 0:
                    break
                in_block, pos = False, end + 2
                kept.append(" ")
            elif in_template:
                end = _TEMPLATE_END.match(line, pos)
                if end is None:
                    break
                in_template, pos = False, end.end()
                kept.append(" ")
            m = tokens.search(line, pos)
            if m is None:
                kept.append(line[pos:])
                break
            kept.append(line[pos:m.start()])
            tok = m.group(0)
            if tok == "/*":
                in_block, pos = True, m.end()
            elif tok in ("//", "--", "#"):
                break
            else:
                kept.append(tok)
                pos = m.end()
                in_template = tok[0] == "`" and m.groupdict().get("tick") is None
        out.append("".join(kept))
    return out
