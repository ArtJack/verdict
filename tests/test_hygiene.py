"""Tests for the hygiene scan — junk, near-certain exposures and reading leads.

Most of what these guard is restraint. Tier 1 files a Critical finding with no
model in the loop, so a false positive there caps a real project's verdict for
nothing; every trap below is one real products ship.
"""

import base64
import hashlib
import json
import os
import random
import string
import subprocess
import threading

import pytest

from verdict_mcp import hygiene
from verdict_mcp.hygiene import hygiene_census, is_test_path


def git(args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path, files: dict):
    r = tmp_path / "app"
    r.mkdir()
    git(["init", "-qb", "main"], r)
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "first"], r)
    return r


def kinds(result, tier=None):
    return sorted(i["kind"] for i in result["items"] if tier is None or i["tier"] == tier)


LIVE = "sk-ant-api03-" + "Qm9vY2FsbDEzW7tVx2Lp8Rz4Kf0HdN5sGj3aYcBwXeTqUiO"  # not a real key


def test_a_live_key_in_source_is_tier_one_and_its_value_never_leaves(tmp_path):
    r = make_repo(tmp_path, {"app/config.py": f'API_KEY = "{LIVE}"\n'})
    out = hygiene_census(r)
    assert kinds(out, 1) == ["secret_in_code"]
    assert LIVE not in json.dumps(out), "the value must be redacted where it is found"
    item = [i for i in out["items"] if i["tier"] == 1][0]
    assert item["path"] == "app/config.py" and item["line"] == 1
    assert item["excerpt"].startswith("anthropic key: <") and item["excerpt"].endswith(f"…{LIVE[-4:]}>")


def test_fake_keys_in_a_redaction_test_are_not_findings(tmp_path):
    r = make_repo(tmp_path, {
        "tests/test_redaction.py": f'key = "{LIVE}"\n',
        "app/docs.py": 'EXAMPLE = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"\n',
    })
    assert kinds(hygiene_census(r), 1) == []


def test_a_placeholder_or_low_entropy_value_is_not_a_secret(tmp_path):
    r = make_repo(tmp_path, {"app/settings.py":
                             'A = "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n'
                             'B = "AKIAIOSFODNN7EXAMPLE"\n'})
    assert kinds(hygiene_census(r), 1) == []


def test_a_committed_env_local_is_tier_one_and_a_template_is_not(tmp_path):
    live = "sk_" + "live_" + "Q2hhbmdlTWVQbGVhc2U4Nw"      # split so no scanner sees a key
    r = make_repo(tmp_path, {".env.local": f"STRIPE_SECRET_KEY={live}\n",
                             ".env.example": "STRIPE_SECRET_KEY=CHANGE_ME\n"})
    out = hygiene_census(r)
    tracked = [i for i in out["items"] if i["kind"] == "secret_file_tracked"]
    assert [i["path"] for i in tracked] == [".env.local"]


def test_a_committed_env_with_only_public_defaults_is_a_lead_not_a_finding(tmp_path):
    r = make_repo(tmp_path, {".env": "VITE_APP_NAME=shop\nVITE_API_URL=https://api.example.com\n"})
    out = hygiene_census(r)
    assert "secret_file_tracked" not in kinds(out)
    assert "env_file_committed" in [lead["kind"] for lead in out["leads"]]


def test_a_secret_named_client_variable_is_tier_one_but_anon_keys_are_not(tmp_path):
    r = make_repo(tmp_path, {"src/lib/client.ts":
                             "const s = process.env.NEXT_PUBLIC_STRIPE_SECRET_KEY;\n"
                             "const a = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;\n"})
    out = hygiene_census(r)
    assert [i["line"] for i in out["items"] if i["kind"] == "public_env_secret"] == [1]
    assert "public_env_key_name" in [lead["kind"] for lead in out["leads"]]


def test_a_service_role_jwt_is_a_secret_and_an_anon_jwt_is_not(tmp_path):
    import base64

    def jwt(role):
        body = base64.urlsafe_b64encode(json.dumps({"role": role, "iss": "supabase"}).encode()).decode().rstrip("=")
        return f"eyJhbGciOiJIUzI1NiJ9.{body}.c2lnbmF0dXJlLXNpZ25hdHVyZQ"
    r = make_repo(tmp_path, {"src/admin.ts": f'const k = "{jwt("service_role")}";\n',
                             "src/public.ts": f'const k = "{jwt("anon")}";\n'})
    out = hygiene_census(r)
    assert [i["path"] for i in out["items"] if i["kind"] == "secret_in_code"] == ["src/admin.ts"]


def test_open_firebase_rules_and_disabled_rls_are_tier_one(tmp_path):
    r = make_repo(tmp_path, {
        "firestore.rules": "service cloud.firestore {\n  match /{d=**} {\n    allow read, write: if true;\n  }\n}\n",
        "supabase/migrations/001_init.sql": "create table orders(id int);\nalter table orders disable row level security;\n",
    })
    out = hygiene_census(r)
    rules = sorted((i["path"], i["line"]) for i in out["items"] if i["kind"] == "open_database_rules")
    assert rules == [("firestore.rules", 3), ("supabase/migrations/001_init.sql", 2)]


def test_a_debugger_left_in_app_code_is_tier_one_minor_but_not_in_tests(tmp_path):
    r = make_repo(tmp_path, {"web/app.js": "function f(){\n  debugger;\n}\n",
                             "svc/run.py": "def f():\n    breakpoint()\n",
                             "tests/test_x.py": "def test_x():\n    breakpoint()\n"})
    out = hygiene_census(r)
    assert sorted(i["path"] for i in out["items"] if i["kind"] == "debugger_statement") == ["svc/run.py", "web/app.js"]


def test_the_test_path_rule():
    assert is_test_path("tests/test_redaction.py") and is_test_path("src/a.test.ts")
    assert is_test_path("eval/fixtures/slop/commits/01/sync.py")
    assert not is_test_path("src/testing_utils_prod.py")


# ── restraint: what tier 1 must never file ────────────────────────────────
# Each case below was a Critical or Minor filed by a regex on a probe or a real
# repository in the 2026-09-27 review. Credentials are built at run time so that
# no scanner, ours or GitHub's, ever sees one in this file.

def token(n, seed, alphabet=string.ascii_letters + string.digits):
    rng = random.Random(seed)
    return "".join(rng.choice(alphabet) for _ in range(n - 2)) + "7q"


def jwt_with(claims):
    head = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{head}.{body}.{token(43, 99)}"


def test_encrypted_env_files_are_neither_findings_nor_leads(tmp_path):
    enc = f"ENC[AES256_GCM,data:{token(40, 1)},iv:{token(43, 2)}=,tag:{token(22, 3)}==,type:str]"
    r = make_repo(tmp_path, {
        ".env.sops": f"STRIPE_SECRET_KEY={enc}\nsops_version=3.8.1\n",
        "deploy/.env.production.local.sops": f"DB_PASSWORD={enc}\n",
        "k8s/secrets.enc.yaml": f"data:\n  password: {enc}\nsops:\n  version: 3.8.1\n",
        ".env": (f'DOTENV_PUBLIC_KEY="03{token(64, 4, "0123456789abcdef")}"\n'
                 f'API_TOKEN="encrypted:{token(120, 5)}"\n'),
    })
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    lead_paths = [lead["path"] for lead in out["leads"]]
    assert ".env.sops" not in lead_paths and "deploy/.env.production.local.sops" not in lead_paths


def test_env_values_that_are_not_credentials_are_leads_not_findings(tmp_path):
    r = make_repo(tmp_path, {
        "svc1/.env": "ACCESS_TOKEN_TTL=3600\nKEYCLOAK_URL=http://localhost:8080\n",
        "svc2/.env.development": 'SECRET_KEY=""\nPOSTGRES_PASSWORD=postgres\n',
        "svc3/.env.staging": "DB_PASSWORD=${DB_PASSWORD}\nJWT_SECRET=supersecretjwtkeyfordevelopment\n",
        "web/.env.production": "NEXT_PUBLIC_SITE_URL=https://shop.acme.io\n",
        "web/.env.local": "NEXT_PUBLIC_API_URL=http://localhost:3000\n",
    })
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    committed = sorted(lead["path"] for lead in out["leads"] if lead["kind"] == "env_file_committed")
    assert committed == ["svc1/.env", "svc2/.env.development", "svc3/.env.staging",
                         "web/.env.local", "web/.env.production"]


def test_a_committed_env_with_live_secrets_is_one_finding_that_names_them_without_values(tmp_path):
    jwt_secret = token(40, 6)
    openai = "sk-" + "proj-" + token(48, 7)
    r = make_repo(tmp_path, {".env": f"PORT=8080\nJWT_SECRET={jwt_secret}\nOPENAI_API_KEY={openai}\n"})
    out = hygiene_census(r)
    tier1 = [i for i in out["items"] if i["tier"] == 1]
    assert [(i["kind"], i["path"]) for i in tier1] == [("secret_file_tracked", ".env")]
    assert "JWT_SECRET" in tier1[0]["excerpt"] and "OPENAI_API_KEY" in tier1[0]["excerpt"]
    blob = json.dumps(out)
    assert jwt_secret not in blob and openai not in blob


def test_keys_that_are_public_by_design_are_leads_not_findings(tmp_path):
    gkey = "AI" + "za" + token(35, 8)
    demo = jwt_with({"iss": "supabase-demo", "role": "service_role", "exp": 1983812996})
    r = make_repo(tmp_path, {
        "web/src/firebase.js": (f'export const firebaseConfig = {{\n  apiKey: "{gkey}",\n'
                                '  authDomain: "acme.firebaseapp.com",\n};\n'),
        "android/app/google-services.json": f'{{"client": [{{"api_key": [{{"current_key": "{gkey}"}}]}}]}}\n',
        "android/app/debug.keystore": "not a real keystore\n",
        "docker-compose.yml": f"services:\n  kong:\n    environment:\n      SUPABASE_SERVICE_KEY: {demo}\n",
    })
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    google = sorted((lead["path"], lead["line"]) for lead in out["leads"] if lead["kind"] == "google_api_key")
    assert google == [("android/app/google-services.json", 1), ("web/src/firebase.js", 2)]
    assert gkey not in json.dumps(out)


def test_public_reads_creates_and_commented_rules_are_leads_or_nothing(tmp_path):
    r = make_repo(tmp_path, {
        "firestore.rules": (
            "rules_version = '2';\n"
            "service cloud.firestore {\n"
            "  match /databases/{database}/documents {\n"
            "    match /products/{id} {\n"
            "      allow read: if true;\n"
            "      allow write: if request.auth != null && request.auth.token.admin == true;\n"
            "    }\n"
            "    match /waitlist/{id} {\n"
            "      allow create: if true;\n"
            "    }\n"
            "    // allow read, write: if true;\n"
            "    /* allow write: if true;\n"
            "       allow delete: if true; */\n"
            "  }\n"
            "}\n"),
        "storage.rules": ("service firebase.storage {\n  match /b/{bucket}/o {\n"
                          "    match /{allPaths=**} {\n      allow read: if true;\n    }\n  }\n}\n"),
        "database.rules.json": '{\n  "rules": {\n    "catalog": {\n      ".read": true\n    }\n  }\n}\n',
    })
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    public = sorted((lead["path"], lead["line"]) for lead in out["leads"]
                    if lead["kind"] == "public_database_rule")
    assert public == [("database.rules.json", 4), ("firestore.rules", 5), ("firestore.rules", 9),
                      ("storage.rules", 4)]


def test_open_writes_and_a_whole_database_read_are_tier_one(tmp_path):
    r = make_repo(tmp_path, {
        "firestore.rules": (
            "service cloud.firestore {\n"
            "  match /databases/{database}/documents {\n"
            "    match /{document=**} {\n"
            "      allow read: if true;\n"
            "    }\n"
            "    match /orders/{id} {\n"
            "      allow update: if true;\n"
            "      allow read, write;\n"
            "    }\n"
            "  }\n"
            "}\n"),
        "database.rules.json": '{\n  "rules": {\n    "scores": {\n      ".write": true\n    }\n  }\n}\n',
    })
    out = hygiene_census(r)
    rules = sorted((i["path"], i["line"]) for i in out["items"] if i["kind"] == "open_database_rules")
    assert rules == [("database.rules.json", 4), ("firestore.rules", 4), ("firestore.rules", 7),
                     ("firestore.rules", 8)]


def test_a_rule_after_a_recursive_block_closes_belongs_to_its_parent(tmp_path):
    r = make_repo(tmp_path, {"firestore.rules": (
        "service cloud.firestore {\n"
        "  match /databases/{database}/documents {\n"
        "    match /users/{uid} {\n"
        "      match /{rest=**} {\n"
        "        allow read: if request.auth.uid == uid;\n"
        "      }\n"
        "      allow read: if true;\n"
        "    }\n"
        "  }\n"
        "}\n")})
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    assert [(lead["kind"], lead["line"]) for lead in out["leads"]] == [("public_database_rule", 7)]


def test_disabled_rls_counts_only_as_the_final_state_of_a_table(tmp_path):
    r = make_repo(tmp_path, {
        "supabase/migrations/001_notes.sql": (
            "-- never disable row level security on a table in the public schema\n"
            "create table notes(id int);\nalter table notes enable row level security;\n"
            "/* alter table notes disable row level security; */\n"),
        "supabase/migrations/002_pay.sql": ("create table payments(id int);\n"
                                            "alter table payments enable row level security;\n"),
        "supabase/migrations/003_fix.sql": 'ALTER TABLE ONLY "payments" DISABLE ROW LEVEL SECURITY;\n',
        "supabase/seed.sql": ("alter table public.profiles disable row level security;\n"
                              "insert into profiles values (1);\n"
                              "alter table profiles enable row level security;\n"),
        "db/migrations/004_orders.down.sql": "alter table orders disable row level security;\n",
    })
    out = hygiene_census(r)
    rules = [(i["path"], i["line"]) for i in out["items"] if i["kind"] == "open_database_rules"]
    assert rules == [("supabase/migrations/003_fix.sql", 1)]


def test_client_variables_are_read_in_code_and_config_only_and_named_once(tmp_path):
    r = make_repo(tmp_path, {
        "README.md": "Never expose NEXT_PUBLIC_STRIPE_SECRET_KEY; keep it server-side.\n",
        "web/src/signup.ts": "export const minLen = Number(import.meta.env.VITE_PASSWORD_MIN_LENGTH ?? 8);\n",
        "web/src/a.ts": "export const p = import.meta.env.VITE_ADMIN_PASSWORD;\n",
        "web/src/b.ts": "const q = import.meta.env.VITE_ADMIN_PASSWORD;\nexport default q;\n",
        ".github/workflows/deploy.yml": "env:\n  NEXT_PUBLIC_JWT_SECRET: ${{ secrets.JWT_SECRET }}\n",
    })
    out = hygiene_census(r)
    found = sorted((i["path"], i["line"], i["excerpt"]) for i in out["items"] if i["kind"] == "public_env_secret")
    assert found == [(".github/workflows/deploy.yml", 2, "NEXT_PUBLIC_JWT_SECRET"),
                     ("web/src/a.ts", 1, "VITE_ADMIN_PASSWORD")]


def test_a_client_secret_is_reported_where_the_app_reads_it(tmp_path):
    r = make_repo(tmp_path, {
        "scripts/deploy.js": "console.log(process.env.VITE_PAY_SECRET_KEY ? 'set' : 'unset');\n",
        "src/lib/config.js": "export const pay = import.meta.env.VITE_PAY_SECRET_KEY;\n",
    })
    found = [(i["path"], i["line"]) for i in hygiene_census(r)["items"] if i["kind"] == "public_env_secret"]
    assert found == [("src/lib/config.js", 1)]


def test_a_debugger_in_a_comment_a_docstring_or_a_block_comment_is_not_a_finding(tmp_path):
    r = make_repo(tmp_path, {
        "svc/debug_tools.py": "def f():\n    # import pdb; pdb.set_trace()\n    return 1\n",
        "svc/doc.py": '"""Drop a breakpoint() here when you need to look around."""\n',
        "svc/imp.py": "import pdb\n",
        "web/src/snippet.js": "/*\n  debugger;\n*/\nexport const x = 1;\n",
    })
    assert kinds(hygiene_census(r), 1) == []


def test_more_test_conventions_are_test_paths(tmp_path):
    for p in ("shop/tests.py", "shop/test.py", "shop/views_tests.py", "web/cypress/e2e/login.cy.ts",
              "src/__mocks__/api.ts", "src/setupTests.ts"):
        assert is_test_path(p), p
    for p in ("src/latest.py", "src/contest.py", "src/attestations.ts"):
        assert not is_test_path(p), p
    r = make_repo(tmp_path, {"shop/tests.py": ("from django.test import TestCase\n\n"
                                               "class T(TestCase):\n    def test_x(self):\n        breakpoint()\n")})
    assert kinds(hygiene_census(r), 1) == []


# ── a secret never leaves, whichever item its line lands in ───────────────

def test_no_secret_value_reaches_the_output_through_junk_or_leads(tmp_path):
    ant = "sk-ant-" + "api03-" + token(40, 11)
    ant2 = "sk-ant-" + "api03-" + token(40, 12)
    stripe = "sk_" + "live_" + token(24, 13)
    gh = "gh" + "p_" + token(36, 14)
    r = make_repo(tmp_path, {
        "app/client.py": f'import requests\nAPI_KEY = "{ant}"\nr = requests.get("https://x", verify=False)\n',
        "web/log.js": f'console.log("stripe", "{stripe}");\n',
        "app/old.py": f'# client = Anthropic(api_key="{ant2}")\n# client.messages.create(model="x")\nx = 1\n',
        "web/todo.ts": f"// TODO rotate {gh} before launch\nexport const y = 1;\n",
    })
    out = hygiene_census(r)
    blob = json.dumps(out)
    for value in (ant, ant2, stripe, gh):
        assert value not in blob
    shown = {i["kind"]: i["excerpt"] for i in out["items"] if i["tier"] == 2}
    assert "<stripe live key>" in shown["console_debug"]
    assert "<anthropic key>" in shown["commented_out_code"]
    assert "<github token>" in shown["todo_comment"]
    assert [lead["kind"] for lead in out["leads"]] == ["tls_verify_off"]


def test_a_lead_carries_the_comment_above_but_never_the_code(tmp_path):
    secret = token(40, 15)
    r = make_repo(tmp_path, {"app/fetch.py": (
        "import requests\n"
        "# staging only: the proxy re-signs\n"
        f'SIGNING = "{secret}"\n'
        'r = requests.get("https://x", verify=False)\n')})
    out = hygiene_census(r)
    lead = [lead for lead in out["leads"] if lead["kind"] == "tls_verify_off"][0]
    assert "staging only" in lead["why"] and "SIGNING" not in lead["why"]
    assert secret not in json.dumps(out)


# ── the scan reads git, never the disk ────────────────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_a_tracked_symlink_is_never_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.env").write_text(f"STRIPE_SECRET_KEY={'sk_' + 'live_' + token(24, 16)}\n",
                                      encoding="utf-8")
    (outside / "private.py").write_text("# TODO: call Bob about the merger\nx = 1\n", encoding="utf-8")
    r = tmp_path / "app"
    (r / "apps" / "web").mkdir(parents=True)
    (r / "tools").mkdir()
    git(["init", "-qb", "main"], r)
    os.symlink(outside / "real.env", r / "apps" / "web" / ".env")
    os.symlink(outside / "private.py", r / "tools" / "notes.py")
    (r / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "links"], r)
    out = hygiene_census(r)
    assert [i for i in out["items"] + out["leads"] if i["path"] in ("apps/web/.env", "tools/notes.py")] == []
    assert "Bob" not in json.dumps(out)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX only")
def test_a_symlink_to_a_fifo_cannot_hang_the_scan(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    r = tmp_path / "app"
    r.mkdir()
    git(["init", "-qb", "main"], r)
    os.symlink(tmp_path / "pipe", r / "data.txt")
    (r / "a.py").write_text("import os\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "fifo"], r)
    result = {}
    worker = threading.Thread(target=lambda: result.update(out=hygiene_census(r)), daemon=True)
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), "the scan blocked on a FIFO"
    assert result["out"]["counts_by_kind"] == {"unused_import": 1}


def test_the_scan_reads_what_is_committed_not_the_working_copy(tmp_path):
    r = make_repo(tmp_path, {".env": "VITE_APP_NAME=shop\n"})
    (r / ".env").write_text(f"STRIPE_SECRET_KEY={'sk_' + 'live_' + token(24, 17)}\n", encoding="utf-8")
    assert kinds(hygiene_census(r), 1) == []


def test_outside_a_git_checkout_the_scan_is_unavailable_and_walks_nothing(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / ".env.local").write_text(f"STRIPE_SECRET_KEY={'sk_' + 'live_' + token(24, 18)}\n", encoding="utf-8")
    out = hygiene_census(d)
    assert out["status"] == "unavailable" and out["reason"]
    assert not out.get("items")


# ── one file can never cost the scan ──────────────────────────────────────

def test_one_hostile_file_never_costs_the_whole_scan(tmp_path):
    deep = '{"a":' + "[" * 3000 + "]" * 3000 + "}"
    nested = ("eyJhbGciOiJIUzI1NiJ9." + base64.urlsafe_b64encode(deep.encode()).decode().rstrip("=")
              + ".c2lnbmF0dXJlLXNpZ25hdHVyZQ")
    r = make_repo(tmp_path, {
        "svc/cr.py": "x = 1\r\r\rtry:\n    pass\nexcept Exception:\n    pass\n",
        "svc/deep.py": "def f(a):\n" + "    y = 1\n" * 8 + "    return " + " + ".join(["a"] * 1000) + "\n",
        "svc/huge.py": "x = " + " + ".join(["a"] * 30000) + "\n",
        "web/jwt.js": f'export const t = "{nested}";\n',
        "svc/ok.py": "import os\n",
    })
    out = hygiene_census(r)
    assert out["status"] == "measured"
    swallow = [(i["path"], i["line"]) for i in out["items"] if i["kind"] == "broad_swallow"]
    assert swallow == [("svc/cr.py", 6)]
    assert ("svc/ok.py", 1) in [(i["path"], i["line"]) for i in out["items"] if i["kind"] == "unused_import"]


def test_the_file_cap_counts_only_files_the_scan_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene, "FILE_CAP", 2)
    files = {f"assets/i{i}.png": "png\n" for i in range(5)}
    files["src/app.js"] = "function f(){\n  debugger;\n}\n"
    out = hygiene_census(make_repo(tmp_path, files))
    assert [i["path"] for i in out["items"] if i["kind"] == "debugger_statement"] == ["src/app.js"]
    assert out["scope"] == {"files": 1, "capped": False, "file_cap": 2, "failed": 0}
    (tmp_path / "many").mkdir()
    many = make_repo(tmp_path / "many", {f"src/m{i}.js": "export const x = 1;\n" for i in range(3)})
    assert hygiene_census(many)["scope"] == {"files": 2, "capped": True, "file_cap": 2, "failed": 0}


# ── identity and small misreadings ────────────────────────────────────────

def test_repeated_lines_are_numbered_in_line_order(tmp_path):
    src = ("def f():\n    try:\n        a()\n    except Exception:\n        pass\n\n"
           "try:\n    b()\nexcept Exception:\n    pass\n")
    r = make_repo(tmp_path, {"svc/m.py": src})
    got = sorted((i["line"], i["fingerprint"]) for i in hygiene_census(r)["items"] if i["kind"] == "broad_swallow")

    def fp(n):
        base = ("broad_swallow", "svc/m.py", "except Exception:", str(n))
        return hashlib.sha1("\0".join(base).encode("utf-8")).hexdigest()[:16]
    assert got == [(4, fp(0)), (9, fp(1))]


def test_a_committed_env_file_keeps_its_identity_when_a_variable_is_added(tmp_path):
    live = "sk_" + "live_" + token(24, 19)
    r = make_repo(tmp_path, {".env.local": f"STRIPE_SECRET_KEY={live}\n"})
    first = [i["fingerprint"] for i in hygiene_census(r)["items"] if i["kind"] == "secret_file_tracked"]
    (r / ".env.local").write_text(f"AWS_SECRET_ACCESS_KEY={token(40, 20)}\nSTRIPE_SECRET_KEY={live}\n",
                                  encoding="utf-8")
    git(["commit", "-qam", "more"], r)
    second = [i["fingerprint"] for i in hygiene_census(r)["items"] if i["kind"] == "secret_file_tracked"]
    assert len(first) == 1 and first == second


def test_a_spread_or_a_jsx_react_import_is_a_use(tmp_path):
    r = make_repo(tmp_path, {
        "web/vite.config.js": ("import { baseConfig } from './base.js';\n"
                               "export default { ...baseConfig, server: { port: 3000 } };\n"),
        "web/src/App.js": "import React from 'react';\nexport const App = () => <div>hi</div>;\n",
    })
    assert "unused_import" not in hygiene_census(r)["counts_by_kind"]


def test_a_byte_order_mark_does_not_hide_a_python_file(tmp_path):
    r = make_repo(tmp_path, {"svc/bom.py": "﻿import os\ntry:\n    x()\nexcept Exception:\n    pass\n"})
    assert hygiene_census(r)["counts_by_kind"] == {"broad_swallow": 1, "unused_import": 1}


def test_a_minified_line_is_skipped_by_junk_and_lead_checks_but_not_by_the_secret_scan(tmp_path):
    live = "sk_" + "live_" + token(24, 21)
    line = 'function a(b){return eval("//x"+b)}' * 3000 + f';const k="{live}";\n'
    out = hygiene_census(make_repo(tmp_path, {"public/app.js": line}))
    assert kinds(out) == ["secret_in_code"]
    assert out["leads"] == []


def test_entry_files_without_a_scanned_suffix_still_document_commands(tmp_path):
    r = make_repo(tmp_path, {"worker.py": "x = 1\n", "cron.py": "y = 2\n",
                             "Dockerfile.prod": "CMD python worker.py\n",
                             "deploy/app.service": "ExecStart=/usr/bin/python3 /srv/cron.py\n"})
    leads = [lead["path"] for lead in hygiene_census(r)["leads"] if lead["kind"] == "module_never_imported"]
    assert leads == []


def test_live_keys_are_found_in_more_kinds_of_file(tmp_path):
    def live(seed):
        return "sk_" + "live_" + token(24, seed)
    sb = "sb_" + "secret_" + token(32, 22)
    r = make_repo(tmp_path, {
        "notebooks/explore.ipynb": json.dumps(
            {"cells": [{"source": [f'stripe.api_key = "{live(23)}"\n']}]}, indent=1),
        "server/main.go": f'const key = "{live(24)}"\n',
        "web/index.html": f'<script>const k = "{live(25)}";</script>\n',
        "web/src/Pay.vue": (f'<script setup>\nconst k = "{live(26)}";\n</script>\n'
                            '<template><div v-html="raw"></div></template>\n'),
        "supabase/functions/admin/index.ts": f'const admin = createClient(url, "{sb}");\n',
    })
    out = hygiene_census(r)
    paths = sorted(i["path"] for i in out["items"] if i["kind"] == "secret_in_code")
    assert paths == ["notebooks/explore.ipynb", "server/main.go", "supabase/functions/admin/index.ts",
                     "web/index.html", "web/src/Pay.vue"]
    assert "raw_html_injection" in [lead["kind"] for lead in out["leads"]]


# ── tier 2: the junk ledger ───────────────────────────────────────────────

def test_junk_kinds_are_counted_and_none_of_them_is_tier_one(tmp_path):
    r = make_repo(tmp_path, {
        "svc/app.py": (
            "import os\nimport json\n\n"
            "def f():\n    try:\n        return 1\n    except Exception:\n        pass\n\n"
            "# TODO: remove\n"
            "# x = compute()\n# save(x)\n"),
        "web/app.ts": ("import { a, b } from './m';\nconsole.log(a);\n"
                       "fetch('/x').catch(() => {});\n// FIXME later\n"),
    })
    out = hygiene_census(r)
    assert kinds(out, 1) == []
    assert out["counts_by_kind"] == {"broad_swallow": 2, "commented_out_code": 1, "console_debug": 1,
                                     "todo_comment": 2, "unused_import": 3}


def test_print_and_a_narrow_except_pass_are_not_junk(tmp_path):
    r = make_repo(tmp_path, {"cli.py": "def main():\n    print('hi')\n    try:\n        open('x')\n"
                                       "    except OSError:\n        pass\n"})
    assert hygiene_census(r)["counts_by_kind"] == {}


def test_a_todo_inside_a_string_is_not_a_comment(tmp_path):
    r = make_repo(tmp_path, {"census_like.py": 'MARKERS = r"\\b(?:TODO|FIXME)\\b"\n'})
    assert "todo_comment" not in hygiene_census(r)["counts_by_kind"]


def test_identical_functions_are_one_ledger_item(tmp_path):
    body = "".join(f"    v{i} = x + {i}\n" for i in range(8)) + "    return v7\n"
    r = make_repo(tmp_path, {"a.py": f"def one(x):\n{body}", "b.py": f"def two(x):\n{body}"})
    out = hygiene_census(r)
    dup = [i for i in out["items"] if i["kind"] == "duplicate_function"]
    assert len(dup) == 1 and "2 identical copies" in dup[0]["excerpt"]


def test_an_oversized_file_is_one_item_that_keeps_its_fingerprint_as_it_grows(tmp_path):
    r = make_repo(tmp_path, {"big.py": "x = 1\n" * 2100})
    first = [i for i in hygiene_census(r)["items"] if i["kind"] == "oversized_file"]
    (r / "big.py").write_text("x = 1\n" * 2300, encoding="utf-8")
    git(["commit", "-qam", "grow"], r)
    second = [i for i in hygiene_census(r)["items"] if i["kind"] == "oversized_file"]
    assert len(first) == len(second) == 1 and first[0]["fingerprint"] == second[0]["fingerprint"]


def test_a_moved_line_keeps_its_fingerprint(tmp_path):
    r = make_repo(tmp_path, {"a.py": "import os\n"})
    fp1 = [i["fingerprint"] for i in hygiene_census(r)["items"]]
    (r / "a.py").write_text("\n\n\nimport os\n", encoding="utf-8")
    git(["commit", "-qam", "move"], r)
    fp2 = [i["fingerprint"] for i in hygiene_census(r)["items"]]
    assert fp1 == fp2 and len(fp1) == 1


def test_line_numbers_survive_u2028_inside_a_string(tmp_path):
    r = make_repo(tmp_path, {"a.py": 's = "one\u2028two"\n\nimport os\n'})
    item = [i for i in hygiene_census(r)["items"] if i["kind"] == "unused_import"][0]
    assert item["line"] == 3


# ── tier 3: leads ─────────────────────────────────────────────────────────

def test_a_swallow_around_a_secret_write_is_a_lead(tmp_path):
    r = make_repo(tmp_path, {"app/auth.py": (
        "def consume(store, remaining):\n    try:\n"
        "        store.set('mfa_recovery_codes', remaining)\n"
        "    except Exception:\n        pass  # best effort\n")})
    leads = hygiene_census(r)["leads"]
    assert [lead["kind"] for lead in leads] == ["swallow_around_sensitive_write"]


def test_a_security_read_that_fails_open_is_a_lead(tmp_path):
    r = make_repo(tmp_path, {"app/login.py": (
        "def login(store):\n    try:\n        secret = store.get('mfa_secret')\n"
        "    except Exception:\n        secret = None\n    return secret\n")})
    assert [lead["kind"] for lead in hygiene_census(r)["leads"]] == ["security_read_fails_open"]


def test_a_placeholder_salt_in_the_env_template_is_a_lead(tmp_path):
    r = make_repo(tmp_path, {".env.example": "SESSION_SALT=CHANGE_ME_NOW\nPORT=8080\n"})
    leads = hygiene_census(r)["leads"]
    assert [(lead["kind"], lead["line"]) for lead in leads] == [("placeholder_security_default", 1)]


def test_line_leads_carry_the_comment_just_above(tmp_path):
    r = make_repo(tmp_path, {"app/api.py": (
        "def status(req):\n    # public on purpose: version string only\n"
        "    return {'Access-Control-Allow-Origin': '*'}\n")})
    lead = [lead for lead in hygiene_census(r)["leads"] if lead["kind"] == "wildcard_cors"][0]
    assert "public on purpose" in lead["why"]


def test_a_documented_cli_is_not_an_unimported_module(tmp_path):
    r = make_repo(tmp_path, {"rotate_keys.py": "print(1)\n", "orphan.py": "x = 1\n",
                             "README.md": "Run `python rotate_keys.py`.\n"})
    leads = [lead["path"] for lead in hygiene_census(r)["leads"] if lead["kind"] == "module_never_imported"]
    assert leads == ["orphan.py"]


def test_leads_are_capped_but_counted(tmp_path):
    r = make_repo(tmp_path, {"app/x.py": "".join(f"a{i} = eval('1')\n" for i in range(80))})
    out = hygiene_census(r)
    assert len(out["leads"]) == 60 and out["leads_total"] == 80


def test_the_scan_scope_is_reported(tmp_path):
    r = make_repo(tmp_path, {"a.py": "x = 1\n"})
    assert hygiene_census(r)["scope"] == {"files": 1, "capped": False, "file_cap": 5000, "failed": 0}
