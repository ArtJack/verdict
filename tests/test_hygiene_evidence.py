"""What a hygiene scan vouches for, file by file — the evidence a resolution needs.

An item the scan did not see this run resolves only on positive evidence: every
file it lives in was scanned, or has left the tree. So the scan says which files
its checks ran over (`scanned_paths`), which Python files the parser refused
(`parse_failed_paths`) and whether every migration was read (`rls_judged`); the
side file keeps them beside the tier-2 rows; and finalize asks git only about the
files the scan did not read. Silence about a file nobody read is never a fix.
"""

import json
import subprocess

from verdict_mcp import harness, hygiene
from verdict_mcp.hygiene import hygiene_census

from test_hygiene import git, make_repo, token  # noqa: E402

PEM_TEMPLATE = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"


# ── the scan: which files its checks ran over ────────────────────────────

def test_the_scan_names_every_file_its_checks_ran_over_key_files_included(tmp_path):
    # A key file is checked by its name or its content and never by the per-file
    # scan, so the secret-file check is the whole of what applies to it: a deleted
    # key in `server.key` is only ever a fix if the check that filed it re-ran.
    r = make_repo(tmp_path, {
        "app/main.py": "x = 1\n",
        "keys/server.pem": PEM_TEMPLATE,
        "keys/tls.key": PEM_TEMPLATE,
        "keys/client.p12": "not really pkcs12\n",
        "android/release.jks": "binary in real life\n",
        "android/upload.keystore": "binary in real life\n",
        "config/service.json": '{"type": "authorized_user"}\n',
    })
    out = hygiene_census(r)
    assert out["scanned_paths"] == ["android/release.jks", "android/upload.keystore", "app/main.py",
                                    "config/service.json", "keys/client.p12", "keys/server.pem",
                                    "keys/tls.key"]
    assert out["parse_failed_paths"] == [] and out["rls_judged"] is True


def test_a_file_the_cap_left_out_or_the_scan_could_not_read_is_not_vouched_for(tmp_path, monkeypatch):
    # data.json is small enough to be a service-account key, so its secret-file
    # check runs past the cap — but the per-file checks that would find a key in
    # its text did not, and an item they filed there last run proves nothing now.
    monkeypatch.setattr(hygiene, "FILE_CAP", 3)
    r = make_repo(tmp_path, {"app/a.py": "x = 1\n", "app/b.py": "y = 2\n", "data/data.json": "{}\n",
                             "app/broken.py": "z = 3\n"})
    real = hygiene._scan_file

    def breaks(rel, *args, **kwargs):
        if rel == "app/broken.py":
            raise RuntimeError("a detector broke")
        return real(rel, *args, **kwargs)
    monkeypatch.setattr(hygiene, "_scan_file", breaks)
    out = hygiene_census(r)
    assert out["scope"]["capped"] is True and out["status"] == "partial"
    assert out["scanned_paths"] == ["app/a.py", "app/b.py"], \
        "data.json was cut by the cap, and broken.py's checks raised"


def test_a_file_too_large_to_read_is_not_vouched_for(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene, "MAX_BYTES", 200)
    r = make_repo(tmp_path, {"small.py": "x = 1\n", "big.py": "x = 1\n" * 100})
    assert hygiene_census(r)["scanned_paths"] == ["small.py"]


def test_a_file_read_and_found_encrypted_is_vouched_for(tmp_path):
    # Encrypting a committed secrets file in place is a fix: the scan read it and
    # found nothing it may file, so what was filed there last run is gone.
    enc = f"ENC[AES256_GCM,data:{token(40, 401)},iv:{token(43, 402)}=,tag:{token(22, 403)}==,type:str]"
    r = make_repo(tmp_path, {"deploy/secrets.yaml": f"db_password: {enc}\nsops:\n    mac: {enc}\n"})
    assert hygiene_census(r)["scanned_paths"] == ["deploy/secrets.yaml"]


def test_a_python_file_the_parser_refuses_is_named(tmp_path):
    # Its line checks ran, so it was scanned — a key on one of its lines is
    # measured — but what only the parser finds was not looked for.
    r = make_repo(tmp_path, {"bad.py": "import os\ndef f(:\n    pass\n", "good.py": "import os\n"})
    out = hygiene_census(r)
    assert out["parse_failed_paths"] == ["bad.py"]
    assert out["scanned_paths"] == ["bad.py", "good.py"]


def test_rls_is_judged_only_when_every_migration_was_read(tmp_path, monkeypatch):
    files = {"db/migrations/001_orders.sql": "create table orders(id int);\n",
             "db/schema.sql": "".join(f"create table t{i}(id int);\n" for i in range(40))}
    assert hygiene_census(make_repo(tmp_path, files))["rls_judged"] is True
    monkeypatch.setattr(hygiene, "MAX_BYTES", 400)
    (tmp_path / "again").mkdir()
    assert hygiene_census(make_repo(tmp_path / "again", files))["rls_judged"] is False


def test_a_client_secret_names_its_variable_and_every_file_that_reads_it(tmp_path):
    r = make_repo(tmp_path, {
        "web/pay.ts": "const k = process.env.NEXT_PUBLIC_STRIPE_SECRET;\n",
        "web/admin.ts": "const k = process.env.NEXT_PUBLIC_STRIPE_SECRET;\n",
        ".github/workflows/ci.yml": "env:\n  NEXT_PUBLIC_STRIPE_SECRET: ${{ secrets.S }}\n",
    })
    [it] = [i for i in hygiene_census(r)["items"] if i["kind"] == "public_env_secret"]
    assert it["variable"] == "NEXT_PUBLIC_STRIPE_SECRET"
    assert it["sites"] == [".github/workflows/ci.yml", "web/admin.ts", "web/pay.ts"]


def test_a_copied_function_names_every_file_a_copy_is_in(tmp_path):
    body = "".join(f"    v{i} = x + {i}\n" for i in range(8)) + "    return v7\n"
    r = make_repo(tmp_path, {"a.py": f"def one(x):\n{body}", "lib/b.py": f"def two(x):\n{body}",
                             "lib/c.py": f"def three(x):\n{body}"})
    [dup] = [i for i in hygiene_census(r)["items"] if i["kind"] == "duplicate_function"]
    assert dup["sites"] == ["a.py", "lib/b.py", "lib/c.py"]


# ── the side file keeps it, and finalize reads it back ────────────────────

def split_facts(tmp_path, files):
    repo = make_repo(tmp_path, files)
    qa = tmp_path / "qa"
    qa.mkdir()
    assert harness.facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    return repo, qa, json.loads((qa / "facts.json").read_text(encoding="utf-8"))["hygiene"]


def test_the_side_file_keeps_what_the_scan_vouches_for_and_finalize_reads_it_back(tmp_path):
    repo, qa, block = split_facts(tmp_path, {"bad.py": "def f(:\n", "ok.py": "import os\n"})
    for key in ("scanned_paths", "parse_failed_paths", "rls_judged"):
        assert key not in block, f"{key} is for the ledger, not for the tester's reading"
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert side["scanned_paths"] == ["bad.py", "ok.py"] and side["parse_failed_paths"] == ["bad.py"]
    assert side["rls_judged"] is True
    ev = harness.hygiene_evidence(block, qa, repo, "HEAD")
    assert ev.scanned == {"bad.py", "ok.py"} and ev.parse_failed == {"bad.py"} and ev.rls_judged is True
    inline = harness.hygiene_evidence(hygiene_census(repo), qa, repo, "HEAD")
    assert (inline.scanned, inline.parse_failed, inline.rls_judged) == (ev.scanned, ev.parse_failed, True), \
        "a block that was never split holds the same lists inline"


def test_a_side_file_that_cannot_be_read_vouches_for_nothing(tmp_path):
    repo, qa, block = split_facts(tmp_path, {"ok.py": "import os\n"})
    (qa / "hygiene-items.json").write_bytes(b"\xff{not json")
    ev = harness.hygiene_evidence(block, qa, repo, "HEAD")
    assert ev.scanned == set() and ev.parse_failed == set() and ev.rls_judged is False
    assert harness.tier2_items(block, qa) is None, "unknown, which is not the same as none"
    (qa / "hygiene-items.json").write_text(json.dumps({"schema": 1, "items": "rows"}), encoding="utf-8")
    assert harness.tier2_items(block, qa) is None


def test_finalize_reads_what_is_gone_from_the_tree_the_scan_read(tmp_path):
    repo, qa, block = split_facts(tmp_path, {"ok.py": "import os\n", "kept.py": "x = 1\n"})
    ev = harness.hygiene_evidence(block, qa, repo, "HEAD")
    assert ev.absent({"gone.py", "kept.py"}) == {"gone.py"}


# ── the tree: what is gone from it ────────────────────────────────────────
# `git cat-file -e HEAD:<path>` is the obvious test and gives the wrong answer
# twice: it reads the path from the top of the work tree, not from the directory
# the scan read, and it fails for a blob a partial clone never fetched — both of
# which would call a file that is still there gone, and resolve what is in it.

def test_a_file_is_absent_only_when_the_tree_the_scan_read_does_not_hold_it(tmp_path):
    r = make_repo(tmp_path, {"svc/app/k.py": "import os\n", "top.py": "x = 1\n"})
    sub = r / "svc" / "app"
    assert hygiene.absent_from_tree(sub, "HEAD", ["k.py", "gone.py"]) == {"gone.py"}, \
        "paths are the scan's own: relative to the directory it read"
    assert hygiene.absent_from_tree(r, "HEAD", ["top.py", "svc/app/k.py"]) == set()
    assert hygiene.absent_from_tree(r, "0" * 40, ["top.py", "gone.py"]) == set(), \
        "a tree git cannot list says nothing is gone"


def test_a_blob_a_partial_clone_never_fetched_is_still_in_the_tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    git(["init", "-qb", "main"], src)
    (src / "small.py").write_text("import os\n", encoding="utf-8")
    (src / "large.py").write_text("x = 1\n" + "# padding\n" * 50, encoding="utf-8")
    git(["add", "-A"], src)
    git(["commit", "-qm", "c"], src)
    git(["config", "uploadpack.allowFilter", "true"], src)
    part = tmp_path / "part"
    subprocess.run(["git", "clone", "-q", "--no-checkout", "--filter=blob:limit=100", src.as_uri(),
                    str(part)], check=True, capture_output=True)
    assert hygiene.absent_from_tree(part, "HEAD", ["large.py", "small.py", "gone.py"]) == {"gone.py"}


# ── a side file is its own facts run's, or none at all ────────────────────
# hygiene-items.json is written beside facts.json by the run that measured both. A
# side file left by an earlier run — a copy restored, a facts write that failed
# after it — describes another tree: read as this run's, it would resolve what this
# run never scanned.

def test_a_side_file_from_another_facts_run_is_no_side_file_at_all(tmp_path):
    repo, qa, _block = split_facts(tmp_path, {"a.py": "import os\n"})
    stale = (qa / "hygiene-items.json").read_text(encoding="utf-8")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "commit",
                    "--allow-empty", "-qm", "another commit"], check=True, capture_output=True)
    assert harness.facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    block = facts["hygiene"]
    bind = {"git_sha": facts["last_run"]["git_sha"], "measured_at": facts["measured_at"]}
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert (side["git_sha"], side["measured_at"]) == (bind["git_sha"], bind["measured_at"])
    assert harness.tier2_items(block, qa, bind) is not None
    (qa / "hygiene-items.json").write_text(stale, encoding="utf-8")
    assert json.loads(stale)["git_sha"] != bind["git_sha"]
    assert harness.tier2_items(block, qa, bind) is None
    ev = harness.hygiene_evidence(block, qa, repo, bind["git_sha"], bind)
    assert (ev.scanned, ev.parse_failed, ev.rls_judged) == (set(), set(), False)


def test_finalize_resolves_nothing_on_a_side_file_from_another_run(tmp_path):
    from test_hygiene_state import commit, run
    repo = make_repo(tmp_path, {"a.py": "import os\n"})
    qa = tmp_path / "qa"
    run(repo, qa)
    stale = (qa / "hygiene-items.json").read_text(encoding="utf-8")
    commit(repo, {"a.py": "x = 1\n"}, "the import is gone")
    assert harness.facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    (qa / "hygiene-items.json").write_text(stale, encoding="utf-8")
    (qa / "judgment.json").write_text(json.dumps({
        "verdict": "pass with risks", "isolation_check": {"result": "pass"}, "release_blockers": [],
        "not_tested": ["concurrency"], "findings": [], "report": ""}), encoding="utf-8")
    assert harness.finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    block = json.loads((qa / "state.json").read_text(encoding="utf-8"))["hygiene"]
    assert block["summary"]["tier2_unread"] is True and block["summary"]["resolved"] == 0
    rows = json.loads((qa / "hygiene-ledger.json").read_text(encoding="utf-8"))["rows"]
    assert [(r["kind"], r["delta"]) for r in rows] == [("unused_import", "STILL_OPEN")]
