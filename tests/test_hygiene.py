"""Tests for the hygiene scan — junk, near-certain exposures and reading leads.

Most of what these guard is restraint. Tier 1 files a Critical finding with no
model in the loop, so a false positive there caps a real project's verdict for
nothing; every trap below is one real products ship.
"""

import json
import subprocess

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
