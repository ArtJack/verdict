"""The hygiene scan's limits and file classes: which suffixes are code, the caps on files and
bytes, the ledger and preview sizes, and the severities and titles each kind is filed with.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import re


CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"}
# Spelled as one display, not `CODE_SUFFIXES | {…}`: the interpreter-floor test
# reads any `|` holding the text "list" (".plist") as a 3.9-breaking type union.
SCANNED_SUFFIXES = {
    *CODE_SUFFIXES,
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".properties", ".xml",
    ".sh", ".md", ".txt", ".tf", ".conf", ".sql", ".rules", "",
    ".go", ".rb", ".php", ".java", ".kt", ".kts", ".swift", ".cs", ".rs", ".dart", ".scala",
    ".gradle", ".html", ".htm", ".ipynb", ".plist", ".xcconfig", ".tfvars", ".hcl", ".bash",
    ".zsh", ".ps1", ".mdx", ".rst"}
FILE_CAP = 5000          # files scanned per run; reaching it is reported, never silent
MAX_BYTES = 1_000_000    # a minified bundle is not source anybody maintains
OVERSIZED_LINES = 2000
DUPLICATE_MIN_LINES = 8
LEAD_CAP = 60            # leads written to facts; the total is always exact
LEDGER_CAP = 5000        # ledger rows; past it the counts stay exact, rows with a history first
PREVIEW_ROWS = 10        # of the oldest open rows, and of the new ones, kept in the state
LONG_LINE = 2000         # a minified line: junk and lead checks pass it by, the secret scan never does

SEVERITY = {
    "secret_in_code": "Critical",
    "secret_file_tracked": "Critical",
    "public_env_secret": "Critical",
    "open_database_rules": "Critical",
    "debugger_statement": "Minor",
}
TITLE = {
    "secret_in_code": "A live credential is committed in the source",
    "secret_file_tracked": "A secrets file is committed to the repository",
    "public_env_secret": "A secret is exposed through a client-side environment variable",
    "open_database_rules": "Database access rules let anyone read or write",
    "debugger_statement": "A debugger statement is left in shipped code",
}
TIER2_KINDS = ("broad_swallow", "unused_import", "oversized_file", "todo_comment",
               "commented_out_code", "console_debug", "duplicate_function")
_LEAD_ORDER = {k: n for n, k in enumerate((
    "swallow_around_sensitive_write", "security_read_fails_open", "jwt_unverified",
    "sql_from_string", "ai_key_in_browser", "paid_api_from_browser", "google_api_key",
    "placeholder_security_default", "forwarded_header_trust", "wildcard_cors",
    "raw_html_injection", "shell_or_eval", "tls_verify_off", "public_env_key_name",
    "public_database_rule", "rls_policy_using_true", "compose_db_port_published",
    "compose_default_password", "env_file_committed", "module_never_imported"))}

_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "fixtures", "__fixtures__",
              "testdata", "e2e", "__mocks__", "mocks", "cypress", "testing"}
_SCRIPT_DIRS = {"scripts", "script", "bin", "tools", "tool"}
_VENDOR_DIRS = {"vendor", "vendors", "third_party"}
_DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc"}
_MINIFIED = re.compile(r"(?:\.min\.(?:js|mjs|cjs)|-min\.js|\.bundle\.js)$", re.IGNORECASE)
# What the file cap keeps first. Five thousand blog posts must not push the app
# out of the scan: code and the files that hold secrets or rules come first,
# config next, documents and data last.
_CODE_CLASS = {*CODE_SUFFIXES, ".go", ".rb", ".php", ".java", ".kt", ".kts", ".swift", ".cs", ".rs",
               ".dart", ".scala"}
_DATA_CLASS = {".md", ".mdx", ".txt", ".rst", ".adoc", ".json", ".html", ".htm", ".ipynb"}
SERVICE_ACCOUNT_MAX = 16_384   # a service-account key is ~2.4 KB; larger JSON is read only if scanned
# Inherited from a git hook or a wrapper, any of these would point git at another
# repository than the one asked for, and the scan would report that one's files.
_GIT_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")
