"""The patterns each tier looks for: secrets and keys, the tier-2 debris, the tier-3 lead
shapes, SQL, compose files, and what scrubbing must take out of an excerpt.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import ast
import re


# ── tier 1 patterns ───────────────────────────────────────────────────────
_SECRET_PATTERNS = (
    ("anthropic key", re.compile(r"sk-ant-(?:api|admin|oat)\d{2}-[A-Za-z0-9_-]{20,}")),
    ("openai key", re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("telegram bot token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")),
    ("stripe live key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("supabase secret key", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}")),
    ("gitlab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("hugging face token", re.compile(r"\bhf_[A-Za-z0-9]{34,}")),
    ("sendgrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")),
    ("google oauth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{28}(?![A-Za-z0-9_-])")),
)
# A Google API key is public by design in a Firebase or Maps web config: a lead
# for the tester, never a finding — and scrubbed from every excerpt all the same.
_GOOGLE_KEY = ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"))
_GOOGLE_WHY = ("a Google API key — public by design in a Firebase or Maps web config (check its API "
               "restrictions), a leak if it is a Gemini or other server key")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----")
_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=]{40,}$")
# A key written on one line with "\n" escapes, the way a service-account JSON or an
# env file holds it: the header, an escaped newline, then 40 characters of key.
_INLINE_KEY = re.compile(_PRIVATE_KEY.pattern + r"\\n[A-Za-z0-9+/=]{40}")
_SERVICE_ACCOUNT = re.compile(r"\"type\"\s*:\s*\"service_account\"")
_SERVICE_ACCOUNT_KEY = re.compile(r"\"private_key\"\s*:\s*\"" + _INLINE_KEY.pattern)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.(eyJ[A-Za-z0-9_-]{10,})\.[A-Za-z0-9_-]{10,}")
_PLACEHOLDER = re.compile(
    r"x{4,}|example|your[_-]|fake|dummy|sample|placeholder|change_?me|redacted|test|insecure",
    re.IGNORECASE)
_SEQUENTIAL = ("0123", "1234", "2345", "3456", "4567", "5678", "6789", "abcd", "bcde", "wxyz")
# Only a name that ENDS in a credential word: VITE_PASSWORD_MIN_LENGTH is a number
# and VITE_SECRET_SANTA_ENABLED a flag, both public on purpose.
_PUBLIC_ENV_SECRET = re.compile(
    r"\b(?:NEXT_PUBLIC|VITE|EXPO_PUBLIC|REACT_APP|NUXT_PUBLIC|PUBLIC)_(?:[A-Z0-9_]*_)?"
    r"(?:SECRET|SECRET_KEY|PRIVATE_KEY|SERVICE_ROLE|SERVICE_ROLE_KEY|PASSWORD|CLIENT_SECRET)\b")
_ENV_FILE = re.compile(r"(?:^|/)\.env(?:\.[\w.-]+)?$")
_ENV_TEMPLATE = re.compile(r"\.(?:example|sample|template|dist|defaults|test|ci)$", re.IGNORECASE)
_ENV_ASSIGN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_CLIENT_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "EXPO_PUBLIC_", "REACT_APP_", "NUXT_PUBLIC_", "PUBLIC_")
# What makes an env name a credential's (_credential_name). A secret word makes it
# one whatever else it says: SITE_ADMIN_PASSWORD is a password. KEY and TOKEN make it
# one unless a public word says otherwise — RECAPTCHA_SITE_KEY and ALGOLIA_SEARCH_KEY
# are meant for the browser. ADMIN and MASTER only qualify a key: an admin's key is
# one (AZURE_SEARCH_ADMIN_KEY, MASTER_KEY), but ADMIN_WALLET holds an address anyone
# may see, and MASTER_PUBLIC_KEY an xpub.
_SECRET_WORDS = frozenset(("SECRET", "PASSWORD", "PASSWD", "PASS", "PWD", "PRIVATE",
                           "CREDENTIALS", "SALT"))
_KEY_WORDS = frozenset(("KEY", "APIKEY", "TOKEN"))
_KEY_QUALIFIERS = frozenset(("ADMIN", "MASTER"))
_PUBLIC_WORDS = frozenset(("PUBLIC", "PUBLISHABLE", "ANON", "SITE", "SEARCH"))
# Values that are public by design whatever the variable is called: a Google
# browser key, a Stripe publishable key, a Mapbox public token (`pk.`; its secret
# tokens start `sk.`), a PostHog project key.
_PUBLIC_VALUES = ("AIza", "pk_live_", "pk_test_", "pk.", "phc_")
_NOT_A_SECRET_TAIL = frozenset((
    "TTL", "URL", "URI", "PATH", "FILE", "DIR", "ID", "NAME", "PREFIX", "EXPIRY", "EXPIRES",
    "LENGTH", "LEN", "SIZE", "MIN", "MAX", "TIMEOUT", "HEADER", "TYPE", "ALG", "ALGORITHM",
    "VERSION", "REGION", "HOST", "PORT", "USER", "USERNAME", "EMAIL", "ENABLED", "COUNT",
    "FORMAT", "MODE", "WALLET", "ADDRESS", "ACCOUNT", "PUBKEY", "PHONE"))
_KEY_CONTAINER = re.compile(r"\.(?:p12|pfx|jks|keystore)$|^id_(?:rsa|dsa|ecdsa|ed25519)$",
                            re.IGNORECASE)
_ENCRYPTED_LAST = frozenset(("sops", "enc", "age", "gpg", "asc", "vault", "encrypted"))
_ENCRYPTED_INNER = frozenset(("sops", "enc"))
# A SOPS file carries its MAC in its own metadata, whatever the format (dotenv,
# YAML, JSON, INI). A value alone (`ENC[AES256_GCM,…`) is only a quote of one.
_SOPS_MAC = re.compile(r"(?:\bsops_mac\s*=\s*|\"mac\"\s*:\s*\"|\bmac\s*[:=]\s*)ENC\[AES256_GCM,")
_READS_TEXT = ("env", "pem", "json")       # the secret-file checks that need a file's content
# Firestore and Storage rules, read as one text so that a statement or a block
# split across lines is still one, and a one-line block (`match /a/{id} { allow
# read: if true; }`) nests like any other. A match path carries braces of its own
# ({id}, {document=**}), and a string may hold braces; neither opens a block.
_RULES_TOKEN = re.compile(
    r"\bmatch\s+(?P<path>(?:[^\s{}]|\{[^{}\n]*\})+)\s*\{"
    r"|\ballow\s+(?P<methods>[a-z]+(?:\s*,\s*[a-z]+)*)\s*(?::\s*if\s+true\s*)?;"
    r"|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'"
    r"|(?P<brace>[{}])")
_RTDB_RULE = re.compile(r"\"\.(?P<op>read|write)\"\s*:\s*(?:true|\"true\")")
_PUBLIC_RULE_WHY = "a rule anyone can use for reads or creates — check the data is meant to be public"
_DOWN_MIGRATION = re.compile(r"(?:^|[/._-])down\.sql$")
# One migration file, two directions (dbmate, goose, sql-migrate): only what is
# above the down marker is ever applied going forward.
_DOWN_SECTION = re.compile(r"^\s*--\s*(?:migrate:down|\+goose\s+down|\+migrate\s+down)\b",
                           re.IGNORECASE)
_RLS_SWITCH = re.compile(
    r"\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?"
    r"((?:\"[^\"]+\"|[\w$]+)(?:\s*\.\s*(?:\"[^\"]+\"|[\w$]+))?)"
    r"\s+(enable|disable)\s+row\s+level\s+security\b", re.IGNORECASE)
_JS_DEBUGGER = re.compile(r"^\s*debugger\s*;?\s*$")
_PY_DEBUGGER_MODULES = ("pdb", "ipdb", "pudb")
# What `_uncomment` looks for, in C-like code and rules, in SQL, and in Python or
# Ruby: the opening of a block comment, a line comment, or a string — kept whole,
# so a `//` in a URL or a `/*` in a glob is not taken for a comment. A template
# literal left open at the end of a line (no `tick`) stays open on the next.
_C_TOKENS = re.compile(
    r"/\*|//|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*(?P<tick>`)?")
_SQL_TOKENS = re.compile(r"/\*|--|\"[^\"]*\"|'[^']*'")
_HASH_TOKENS = re.compile(r"#|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
# Env files, YAML, TOML, the INI family and shell comment with `#`, and so do
# Dockerfiles, Makefiles, Justfiles and Procfiles, which go by name
# (_hash_commented). There a `#` opens a comment only at the start of the line or
# after whitespace, and never inside quotes: `http://x/#anchor` and "a#b" are text.
# A single-quoted string takes no escapes. Terraform and HCL take `#`, `//` and
# `/* */` anywhere outside a string, and their strings are double-quoted only.
_HASH_COMMENTED = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".sh",
                   ".bash", ".zsh", ".env"}
_HASH_COMMENTED_NAMES = {"makefile", "gnumakefile", "justfile", ".justfile", "procfile"}
_CONFIG_TOKENS = re.compile(r"(?:^|(?<=\s))#|\"(?:\\.|[^\"\\])*\"|'[^']*'")
_HCL_SUFFIXES = {".tf", ".tfvars", ".hcl"}
_HCL_TOKENS = re.compile(r"/\*|//|#|\"(?:\\.|[^\"\\])*\"")
_TEMPLATE_END = re.compile(r"(?:\\.|[^`\\])*`")
_TRIPLE_QUOTED = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')

# ── tier 2 patterns ───────────────────────────────────────────────────────
_JS_EMPTY_CATCH = re.compile(
    r"catch\s*(?:\([^)]*\))?\s*\{\s*\}"
    r"|\.catch\(\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)?\s*=>\s*\{\s*\}\s*\)")
_TODO = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b")
_JS_COMMENT_TODO = re.compile(r"(?://|/\*|^\s*\*).*?\b(?:TODO|FIXME|HACK|XXX)\b")
_CONSOLE = re.compile(r"\bconsole\.(?:log|debug|trace)\(")
_JS_CODEY_COMMENT = re.compile(
    r"^\s*//\s*(?:const |let |var |import |export |return |await |if \(|for \(|\}|"
    r"[\w.$]+\(.*\);?\s*$|[\w.$]+\s*=\s*.+;\s*$)")
_JS_IMPORT = re.compile(
    r"^[ \t]*import\s+(?:type\s+)?(?P<spec>\{[^}]*\}|[\w$]+(?:\s*,\s*\{[^}]*\})?|\*\s+as\s+[\w$]+)"
    r"\s+from\s+['\"][^'\"]+['\"]", re.MULTILINE)
# A use of an imported name: not a member of something else (`x.name`), except
# that a spread (`...name`) is a use like any other.
_JS_USE = r"(?:(?<![\w$.])|(?<=\.\.\.))"
_RICH = (ast.Call, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Import, ast.ImportFrom,
         ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Return, ast.If, ast.For,
         ast.While, ast.With, ast.Raise, ast.Delete, ast.Await)

# ── tier 3 patterns ───────────────────────────────────────────────────────
_WRITE_CALL = re.compile(
    r"\.\s*(?:set|save|write|delete|remove|rename|commit|put|update|insert|replace|dump|store|unlink)\w*\s*\("
    r"|\b(?:save|write|store|persist)\w*\s*\(", re.IGNORECASE)
_READ_CALL = re.compile(r"\.\s*(?:get|read|load|fetch|lookup)\w*\s*\(|\b(?:get|read|load)_\w*\s*\(",
                        re.IGNORECASE)
_SENSITIVE = re.compile(
    r"secret|token|passw|totp|otp|auth|session|credential|recovery|api[_-]?key|private"
    r"|crash|state|ledger|balance|payment", re.IGNORECASE)
_LINE_LEADS = (
    ("wildcard_cors", re.compile(
        r"Access-Control-Allow-Origin['\"]?\s*[:,=]\s*['\"]\*['\"]|allow_origins?\s*=\s*\[?\s*['\"]\*"
        r"|origin\s*:\s*['\"]\*['\"]"),
     "a wildcard CORS rule — check what the route returns and whether it needs a login"),
    ("raw_html_injection", re.compile(
        r"dangerouslySetInnerHTML|\bv-html\s*=|\.innerHTML\s*=(?!=)|\{@html\s|\bset:html\s*="),
     "raw HTML goes into the page — check that what reaches it is sanitized"),
    ("shell_or_eval", re.compile(
        r"shell\s*=\s*True|\bos\.system\(|(?<![\w.])eval\(|(?<![\w.])exec\("
        r"|child_process\.(?:exec|execSync)\(|\bexecSync\(\s*`"),
     "a shell or eval call — check whether any part of the string can come from outside"),
    ("tls_verify_off", re.compile(
        r"verify\s*=\s*False|\bssl\s*=\s*False|CERT_NONE|rejectUnauthorized\s*:\s*false"
        r"|NODE_TLS_REJECT_UNAUTHORIZED"),
     "TLS verification is turned off"),
    ("forwarded_header_trust", re.compile(r"X-Forwarded-(?:Proto|For|Host)|CF-Connecting-IP|X-Real-IP",
                                          re.IGNORECASE),
     "a forwarded header is read — check that it is honoured only behind a trusted proxy"),
    ("public_env_key_name", re.compile(
        r"\b(?:NEXT_PUBLIC|VITE|EXPO_PUBLIC|REACT_APP|NUXT_PUBLIC)_[A-Z0-9_]*(?:KEY|TOKEN)[A-Z0-9_]*"),
     "a client-side variable named like a credential — publishable and anon keys are fine, secret keys are not"),
    # These two, the SQL, browser and compose leads below came from comparing this scan
    # with vibe-audit (github.com/haraldalder-vibemogger/vibe-audit, MIT) on 2026-10-27:
    # the checks it had and this scan did not, each narrowed until our own repositories
    # gave it nothing to say that was not worth a look.
    ("jwt_unverified", re.compile(
        r"[\"']alg[\"']\s*:\s*[\"']none[\"']|algorithms\s*[=:]\s*\[[^\]]*[\"']none[\"']"
        r"|[\"']verify_(?:signature|exp)[\"']\s*:\s*False|ignoreExpiration\s*:\s*true"),
     "a JWT is accepted without its signature or its expiry checked — check this path never "
     "decides who the caller is"),
    ("ai_key_in_browser", re.compile(r"dangerouslyAllowBrowser\s*:\s*true"),
     "an AI SDK is allowed to run in the browser — the key it holds ships to every visitor"),
)
# A value formatted into SQL text. Only DML, and only a value in a value's place — after
# `=`, a comparison, LIKE, IN ( or VALUES (, or inside quotes — so a table or column name
# in DDL, a clause assembled from fixed parts, a bound parameter and an ALL_CAPS constant
# all say nothing: identifiers cannot be bound, and those were most of what the first
# version flagged on our own repositories.
_SQL_SHAPE = re.compile(r"\b(?:select\b[\s\S]{0,400}?\bfrom|insert\s+into|update\s+[\w.\"`\[\]]+\s+set"
                        r"|delete\s+from)\b", re.IGNORECASE)
_SQL_SLOT = re.compile(r"(?:=|<>|!=|<|>|\blike|\bin\s*\(|\bvalues\s*\()\s*['\"%]*$|['\"]%?$", re.IGNORECASE)
_SQL_IN_VALUES = re.compile(r"\bvalues\s*\([^)]*,\s*['\"]?$", re.IGNORECASE)
_SQL_SLOT_LINE = re.compile(r"(?:(?:=|<>|!=|<|>|\blike|\bin\s*\(|\bvalues\s*\()\s*['\"%]*|['\"]%?)\{(?!\{)",
                            re.IGNORECASE)
_SQL_PERCENT = re.compile(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sr]")
_SQL_BRACES = re.compile(r"\{[^{}]*\}")
_CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_JS_TEMPLATE = re.compile(r"`([^`]*)`?")
_JS_SQL_CONCAT = re.compile(r"([\"'])((?:(?!\1)[^\\]|\\.)*)\1\s*\+\s*[A-Za-z_$(]")
_SQL_WHY = ("a value is formatted into SQL text — check whether it can come from outside; "
            "pass it as a query parameter instead")
# A call to a paid API from code that runs in the browser: whatever key it sends,
# every visitor can read.
_PAID_API = re.compile(r"https?://api\.(?:openai|anthropic|stripe)\.com")
_USE_CLIENT = re.compile(r"""^(['"])use client\1;?$""")
# Compose files: a database password left at a well-known default, and a database port
# published on every interface (Docker's own rules sit ahead of the host's firewall).
_COMPOSE_FILE = re.compile(r"^(?:docker-)?compose(?:[.-][\w.-]+)?\.ya?ml$", re.IGNORECASE)
_COMPOSE_PASSWORD = re.compile(
    r"^\s*-?\s*[\"']?(?:POSTGRES|MYSQL(?:_ROOT)?|MARIADB(?:_ROOT)?|MONGO_INITDB_ROOT|REDIS|RABBITMQ_DEFAULT"
    r"|WORDPRESS_DB|PG)_?PASS(?:WORD)?[\"']?\s*[:=]\s*[\"']?(?P<value>[^\"'\s#]*)[\"']?\s*(?:#.*)?$")
_DEFAULT_PASSWORDS = frozenset(("postgres", "password", "root", "admin", "secret", "example", "changeme",
                                "test", "pass", "123456", "12345678", "mysql", "mongo", "guest",
                                "wordpress"))
_COMPOSE_PORTS = re.compile(r"^(?P<indent>\s*)ports\s*:\s*(?:#.*)?$")
_COMPOSE_PORT = re.compile(
    r"^\s*-\s*[\"']?(?:(?P<ip>[\d.]+|\[[0-9a-fA-F:]*\]|localhost):)?(?:\d+(?:-\d+)?:)?"
    r"(?P<container>\d+)(?:-\d+)?(?:/(?:tcp|udp))?[\"']?\s*(?:#.*)?$")
_DB_PORTS = frozenset((5432, 3306, 27017, 6379, 9200, 9300, 6333, 6334, 5672, 15672, 11211, 9042,
                       8086, 1433, 5984, 7687, 26257, 28015, 8529))
_COMMENT_MARKS = ("#", "//", "/*", "*", "--")
_RLS_OPEN_POLICY = re.compile(r"using\s*\(\s*true\s*\)", re.IGNORECASE)
_PLACEHOLDER_SECURITY_DEFAULT = re.compile(
    r"^\s*([A-Z0-9_]*(?:SALT|SECRET|KEY|TOKEN|PASSWORD|PASS)[A-Z0-9_]*)\s*=\s*['\"]?"
    r"(?:change_?me\w*|changeme\w*|your[_-]\w*|x{3,}|secret|password|replace_?me\w*|todo)['\"]?\s*$",
    re.IGNORECASE)
_ENTRY_FILE = re.compile(
    r"(?:^|/)(?:Makefile|Dockerfile[\w.-]*|docker-compose[\w.-]*|Procfile|[\w.-]*\.service[\w.-]*"
    r"|pyproject\.toml|setup\.cfg|package\.json|README[\w.-]*)$|\.sh$|^\.github/workflows/",
    re.IGNORECASE)

# ── scrubbing: what may leave in an excerpt or a reason ───────────────────
_SCRUBBED = _SECRET_PATTERNS + (_GOOGLE_KEY,)
_SCRUB_RUN = re.compile(r"[A-Za-z0-9+_=-]{24,}")
# A base64 secret split by `/` (an AWS secret access key) is no run for the rule
# above; as one run it is mixed case, carries digits, and is near-random.
_SCRUB_BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{30,}={0,2}(?![A-Za-z0-9+/=])")
_URL_CREDENTIALS = re.compile(r"(://[^/\s:@]*:)[^@\s/]+@")
