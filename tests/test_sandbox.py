"""The box target code runs in (0.94.0, `sandbox.py`).

Measured 2026-11-03 under `verdict-paid`, before this:
  * the project's gates, its test collection, fix verification, coverage, the census and a
    tester's repro all ran with the caller's environment, `ANTHROPIC_API_KEY` included;
  * they had the network;
  * they could read every file the owner can.

A review of the first cut then measured four ways back out:
  * a boxed gate planting a git hook and `.claude` settings that ran outside the box;
  * a shipped `profile.md` turning the box off;
  * a writable `~` reopening `~/.ssh`;
  * a `.CLAUDE` directory and a symlink passing the shipped-configuration check.
Each is a test here.
"""

import json
import os
import subprocess
import sys
import time

import pytest

from conftest import git
from verdict_mcp import harness, profile, runner, sandbox


def _box_works() -> bool:
    """Decided apart from `sandbox.available`/`nested`: a mutant of either must not be what
    skips the tests that would catch it."""
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    probe = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)",
                            "/usr/bin/true"], capture_output=True, text=True)
    return probe.returncode == 0


MAC_BOX = pytest.mark.skipif(not _box_works(),
                             reason="needs macOS sandbox-exec, outside another sandbox")
SECRET = "CANARY_SECRET_TOKEN"


@pytest.mark.skipif(not os.environ.get("VERDICT_TEST_REQUIRE_BOX"),
                    reason="only where CI says this machine must have the box")
def test_the_ci_machine_that_must_have_the_box_has_it():
    """The macOS CI job sets VERDICT_TEST_REQUIRE_BOX: there a missing box is a failure, never
    a row of skips that reads as green."""
    assert _box_works() and sandbox.available() and not sandbox.nested()


def _repo(tmp_path, name="proj"):
    repo = tmp_path / name
    repo.mkdir()
    git(["init", "-qb", "main"], repo)
    (repo / "README").write_text("x\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "init"], repo)
    return repo


def _script(repo, body: str, name="probe.py") -> str:
    """A gate command that runs `body` as a Python file in the checkout, on any OS."""
    (repo / name).write_text(body, encoding="utf-8")
    return f'"{sys.executable}" {name}'


# ── the environment: built from the allowlist, never the caller's ───────────────

def test_the_environment_keeps_the_allowlist_and_drops_every_secret():
    source = {"PATH": "/bin", "HOME": "/h", "LANG": "C", "LC_ALL": "C", "PYTHONPATH": "/p",
              "ANTHROPIC_API_KEY": "sk", "OP_SERVICE_ACCOUNT_TOKEN": "op",
              "GITHUB_TOKEN": "gh", "AWS_SECRET_ACCESS_KEY": "aws", "CLAUDE_CONFIG_DIR": "/c",
              "DJANGO_SETTINGS_MODULE": "s", "VERDICT_REPLAY_ORIGINAL": "/o",
              "UV_INDEX_URL": "https://u:p@index", "UV_CACHE_DIR": "/shared"}
    env = sandbox.environment({"PYTHONDONTWRITEBYTECODE": "1"}, source=source)
    assert env == {"PATH": "/bin", "HOME": "/h", "LANG": "C", "LC_ALL": "C", "PYTHONPATH": "/p",
                   "VERDICT_REPLAY_ORIGINAL": "/o", "PYTHONDONTWRITEBYTECODE": "1"}
    named = sandbox.environment(names=["DJANGO_SETTINGS_MODULE", "ANTHROPIC_API_KEY"],
                                source=source)
    assert named["DJANGO_SETTINGS_MODULE"] == "s" and "ANTHROPIC_API_KEY" not in named


def test_a_gate_does_not_see_the_callers_secret_and_off_restores_the_old_way(
        tmp_path, monkeypatch):
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv(SECRET, "leak")
    cmd = _script(repo, f"import os, sys\nsys.exit(3 if os.environ.get({SECRET!r}) else 0)\n")
    facts = harness.collect(repo, qa_root, [("suite", cmd)])
    assert facts["gates"]["suite"]["result"] == "pass"
    sandbox.configure(sandbox.Policy(mode="off"))
    facts = harness.collect(repo, qa_root, [("suite", cmd)])
    assert facts["gates"]["suite"]["exit_code"] == 3


def test_the_profile_names_what_a_suite_needs_but_never_a_credential(tmp_path, monkeypatch):
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "proj.settings")
    cmd = _script(repo, "import os, sys\nsys.exit(0 if os.environ.get('DJANGO_SETTINGS_MODULE')"
                        " == 'proj.settings' else 4)\n")
    assert harness.collect(repo, qa_root, [("suite", cmd)])["gates"]["suite"]["exit_code"] == 4
    notes = []
    sandbox.configure(sandbox.Policy(env_names=["DJANGO_SETTINGS_MODULE", "ANTHROPIC_API_KEY"],
                                     notes=notes))
    assert harness.collect(repo, qa_root, [("suite", cmd)])["gates"]["suite"]["result"] == "pass"
    assert sandbox.current().env_names == {"DJANGO_SETTINGS_MODULE"}
    assert any("never passed" in n for n in notes)


def test_a_fix_verification_test_does_not_see_the_callers_secret(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv(SECRET, "leak")
    (repo / "check.py").write_text(
        f"import os, sys\nok = not os.environ.get({SECRET!r})\n"
        "print('1 passed' if ok else '1 failed')\nsys.exit(0 if ok else 1)\n", encoding="utf-8")
    result = harness._run_test(f'"{sys.executable}" check.py {{id}}', "t", repo, repo, 60)
    assert result["result"] == "pass", result


def test_a_census_mutants_tests_do_not_see_the_callers_secret(tmp_path, monkeypatch):
    from verdict_mcp import gaps
    scratch = tmp_path / "fresh" / "tree"
    scratch.mkdir(parents=True)
    monkeypatch.setenv(SECRET, "leak")
    (scratch / "check.py").write_text(
        f"import os, sys\nsys.exit(1 if os.environ.get({SECRET!r}) else 0)\n", encoding="utf-8")
    verdict = gaps._run_tests(f'"{sys.executable}" check.py {{id}}', ["t"], scratch,
                              gaps._env(tmp_path, scratch))
    assert verdict == "pass"


def test_each_run_gets_its_own_uv_cache(tmp_path):
    repo = _repo(tmp_path)
    cmd = _script(repo, "import os\nprint(os.environ.get('UV_CACHE_DIR', ''))\n")
    proc = sandbox.run(cmd, cwd=repo, shell=True, writable=[repo], timeout=60)
    assert "verdict-box-" in proc.stdout and proc.stdout.strip().endswith("uv-cache")


def test_required_with_no_box_runs_nothing_and_says_why(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(sandbox, "available", lambda: False)
    proc = sandbox.run(_script(repo, "open('ran', 'w').write('1')\n"), cwd=repo, shell=True,
                       writable=[repo], policy=sandbox.Policy(mode="required"))
    assert proc.returncode == 126 and "sandbox: required" in proc.stderr
    assert proc.sandbox == "refused" and not (repo / "ran").exists()
    env_only = sandbox.run(_script(repo, "open('ran', 'w').write('1')\n"), cwd=repo,
                           shell=True, writable=[repo], policy=sandbox.Policy())
    assert env_only.returncode == 0 and env_only.sandbox == "env-only"
    forced = sandbox.run(_script(repo, "open('again', 'w').write('1')\n"), cwd=repo, shell=True,
                         writable=[repo], policy=sandbox.Policy(mode="off"), force_box=True)
    assert forced.sandbox == "refused" and not (repo / "again").exists()


def test_a_nested_harness_runs_only_inside_a_box_verdict_set_up(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(sandbox, "available", lambda: True)
    monkeypatch.setattr(sandbox, "nested", lambda: True)
    cmd = _script(repo, "print('ran')\n")
    refused = sandbox.run(cmd, cwd=repo, shell=True, writable=[repo],
                          policy=sandbox.Policy(mode="required"))
    assert refused.sandbox == "refused" and "did not set up" in refused.stderr
    monkeypatch.setenv(sandbox.OUTER_ENV, "claude-code")
    ours = sandbox.run(cmd, cwd=repo, shell=True, writable=[repo],
                       policy=sandbox.Policy(mode="required"))
    assert ours.sandbox == "outer" and "ran" in ours.stdout


def test_a_nested_box_is_detected_not_stacked(monkeypatch):
    monkeypatch.setattr(sandbox, "_NESTED", [])
    monkeypatch.setattr(sandbox, "available", lambda: True)

    def refused(*_a, **_k):
        return subprocess.CompletedProcess([], 71, "", "sandbox_apply: Operation not permitted")
    monkeypatch.setattr(sandbox.subprocess, "run", refused)
    assert sandbox.nested() is True


# ── the floor: a profile can tighten the box, never loosen it ──────────────────

def test_a_floor_outranks_the_profile_and_required_drops_its_loosening():
    notes = []
    pol = sandbox.Policy(mode="off", network_gates=["install"], write=["~/.cache/uv"],
                         env_names=["DJANGO_SETTINGS_MODULE"], floor="required", notes=notes)
    assert pol.mode == "required" and not pol.network_gates and not pol.write
    assert not pol.env_names and any("below the floor" in n for n in notes)
    assert sandbox.Policy(mode="off", floor="auto").mode == "auto"
    assert sandbox.Policy(mode="required", floor="auto").mode == "required"


def test_the_floor_comes_from_the_environment_verdict_run_sets(tmp_path, monkeypatch):
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text("---\nsandbox: off\n---\n", encoding="utf-8")
    assert sandbox.from_profile(qa).mode == "off"
    monkeypatch.setenv(sandbox.FLOOR_ENV, "auto")
    assert sandbox.from_profile(qa).mode == "auto"


def test_a_writable_path_that_reaches_a_credential_store_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".ssh").mkdir(parents=True)
    notes = []
    pol = sandbox.Policy(write=["~", str(tmp_path / "home" / ".ssh" / "x"), str(tmp_path / "ok")],
                         notes=notes)
    assert [str(p) for p in pol.write] == [os.path.realpath(str(tmp_path / "ok"))]
    assert sum("credential store" in n for n in notes) == 2


# ── the box: what the SBPL text says ───────────────────────────────────────

def test_the_profile_text_denies_the_network_but_loopback_and_the_secret_stores(tmp_path):
    text = sandbox.profile([tmp_path], home=tmp_path / "home", source={})
    assert "(deny network*)" in text
    assert '(allow network-outbound (remote ip "localhost:*"))' in text
    # The measured mistake: an allowance on the LOCAL end of every network operation let a
    # TCP connection to 1.1.1.1 through. Outbound is matched on the remote end only.
    assert '(allow network* (local ip' not in text
    assert text.index("(deny network*)") < text.index("(allow network-outbound")
    for store in (".ssh", ".aws", ".config/op-agent", ".claude/verdict"):
        assert sandbox._quote(os.path.realpath(str(tmp_path / "home" / store))) in text
    assert r"\.config/.*\.env$" in text
    assert text.index('(deny file-write* (subpath "/"))') < text.index("(allow file-write*")
    assert "(deny file-read* " in text
    assert text.index("(deny file-read* ") < text.index("(allow file-read* ")
    # The credential stores are denied again after the read-back, so a writable path that
    # contains one cannot reopen it; other projects' records are not re-denied (the run's own
    # QA root lives among them).
    tail = text[text.rindex("(allow file-read* "):]
    assert sandbox._quote(os.path.realpath(str(tmp_path / "home" / ".ssh"))) in tail
    assert sandbox._quote(os.path.realpath(str(tmp_path / "home" / ".claude" / "verdict"))) not in tail
    assert "(allow network-outbound" not in sandbox.profile([tmp_path], loopback=False,
                                                           home=tmp_path, source={})
    assert "(deny network*)" not in sandbox.profile([tmp_path], network=True, home=tmp_path,
                                                    source={})


def test_the_profile_text_keeps_git_claude_and_the_qa_root_unwritable(tmp_path):
    repo, qa = tmp_path / "repo", tmp_path / "qa"
    text = sandbox.profile([repo], guarded=[repo], no_write=[qa], home=tmp_path, source={})
    allow = text.index("(allow file-write* ")
    deny = text.index("(deny file-write* ", allow)
    for name in (".git", ".claude", ".mcp.json"):
        assert f"(subpath {sandbox._quote(os.path.realpath(str(repo / name)))})" in text[deny:]
    assert f"(subpath {sandbox._quote(os.path.realpath(str(qa)))})" in text[deny:]


def test_the_claude_login_the_caller_runs_under_is_a_secret_store(tmp_path):
    paths = sandbox.secret_paths(home=tmp_path, source={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    assert os.path.realpath(str(tmp_path / "cfg")) in paths


def test_the_harness_git_runs_no_hook_a_repository_names(tmp_path, monkeypatch):
    env = {}
    sandbox.harden_git(env)
    sandbox.harden_git(env)          # idempotent
    keys = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert keys == {"core.hooksPath": "/dev/null", "core.fsmonitor": "false"}
    repo = _repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{tmp_path / 'hook-ran'}'\n", encoding="utf-8")
    hook.chmod(0o755)
    plain = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach",
                    str(tmp_path / "wt1")], check=True, capture_output=True, env=plain)
    if not (tmp_path / "hook-ran").exists():
        pytest.skip("this git runs no post-checkout hook on `worktree add`: nothing to defend")
    (tmp_path / "hook-ran").unlink()
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach",
                    str(tmp_path / "wt2")], check=True, capture_output=True,
                   env={**plain, **env})
    assert not (tmp_path / "hook-ran").exists()


def test_configuring_the_box_hardens_the_harnesss_own_git(monkeypatch):
    for i in range(int(os.environ.get("GIT_CONFIG_COUNT") or 0)):
        monkeypatch.delenv(f"GIT_CONFIG_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GIT_CONFIG_VALUE_{i}", raising=False)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    sandbox.configure(None)
    keys = [os.environ.get(f"GIT_CONFIG_KEY_{i}") for i in range(int(os.environ["GIT_CONFIG_COUNT"]))]
    assert "core.hooksPath" in keys and "core.fsmonitor" in keys


def test_premeasure_starts_with_no_credential_in_its_environment(tmp_path, monkeypatch):
    seen = {}

    def fake_premeasure(repo, qa_root, env, sha_range):
        seen.update(env)
        return "abc123"
    monkeypatch.setattr(runner, "premeasure", fake_premeasure)
    repo = _repo(tmp_path)
    env = {"PATH": "/bin", "ANTHROPIC_API_KEY": "sk", "OP_SERVICE_ACCOUNT_TOKEN": "op",
           "VERDICT_MODEL": "opus"}
    assert runner.measure_first(repo, tmp_path, env, None, "auto")
    assert "ANTHROPIC_API_KEY" not in seen and "OP_SERVICE_ACCOUNT_TOKEN" not in seen
    assert seen["VERDICT_MODEL"] == "opus" and env[runner.PREMEASURED_ENV] == "abc123"


# ── the box on a Mac: what the code under test can and cannot do ────────────────────

PROBE = r'''
import json, os, socket, sys, threading
socket.setdefaulttimeout(3)
out = {}
def t(name, fn):
    try:
        out[name] = fn()
    except Exception as exc:
        out[name] = "denied " + type(exc).__name__
home, qa = sys.argv[1], sys.argv[2]
t("secret_env", lambda: os.environ.get("CANARY_SECRET_TOKEN", "absent"))
t("ssh", lambda: open(os.path.join(home, ".ssh", "id_test")).read())
t("config_env_file", lambda: open(os.path.join(home, ".config", "jobs", "bot.env")).read())
t("other_record", lambda: open(os.path.join(home, ".claude", "verdict", "other", "state.json")).read())
t("own_record", lambda: open(os.path.join(qa, "repro.py")).read())
t("write_qa_root", lambda: open(os.path.join(qa, "profile.md"), "w").write("sandbox: off"))
t("write_checkout", lambda: open("written", "w").write("1"))
t("write_git_hook", lambda: open(os.path.join(".git", "hooks", "post-checkout"), "w").write("x"))
t("write_claude", lambda: os.makedirs(".claude", exist_ok=True) or open(os.path.join(".claude", "settings.local.json"), "w").write("{}"))
t("write_home", lambda: open(os.path.join(home, "stray"), "w").write("1"))
t("tcp", lambda: socket.create_connection(("1.1.1.1", 53), timeout=3) and "connected")
t("dns", lambda: socket.getaddrinfo("example.com", 80) and "resolved")
def loop():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    th = threading.Thread(target=lambda: srv.accept()[0].sendall(b"ok")); th.start()
    data = socket.create_connection(("127.0.0.1", port), timeout=3).recv(2); th.join()
    return data.decode()
t("loopback", loop)
print(json.dumps(out))
'''


def _home(tmp_path):
    home = tmp_path / "home"
    for d in (".ssh", ".config/jobs", ".claude/verdict/other", ".claude/verdict/mine"):
        (home / d).mkdir(parents=True)
    (home / ".ssh" / "id_test").write_text("SSH", encoding="utf-8")
    (home / ".config" / "jobs" / "bot.env").write_text("T=1", encoding="utf-8")
    (home / ".claude" / "verdict" / "other" / "state.json").write_text("{}", encoding="utf-8")
    (home / ".claude" / "verdict" / "mine" / "repro.py").write_text("ok", encoding="utf-8")
    return home, home / ".claude" / "verdict" / "mine"


@MAC_BOX
def test_inside_the_box_the_code_reaches_nothing_but_its_checkout_and_loopback(
        tmp_path, monkeypatch):
    home, qa = _home(tmp_path)
    repo = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(SECRET, "leak")
    (repo / "probe.py").write_text(PROBE, encoding="utf-8")
    proc = sandbox.run([sys.executable, "probe.py", str(home), str(qa)], cwd=repo,
                       writable=[repo], policy=sandbox.Policy(qa_root=qa), timeout=60)
    assert proc.sandbox == "sandbox-exec", proc.stderr
    seen = json.loads(proc.stdout)
    assert seen["secret_env"] == "absent"
    for denied in ("ssh", "config_env_file", "other_record", "write_qa_root", "write_git_hook",
                   "write_claude", "write_home", "tcp", "dns"):
        assert str(seen[denied]).startswith("denied"), (denied, seen[denied])
    assert seen["own_record"] == "ok" and seen["write_checkout"] == 1
    assert seen["loopback"] == "ok"


@MAC_BOX
def test_a_writable_home_does_not_reopen_the_credential_stores(tmp_path, monkeypatch):
    home, qa = _home(tmp_path)
    repo = _repo(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    (repo / "probe.py").write_text(PROBE, encoding="utf-8")
    # `sandbox_write` itself refuses `~`; this is the SBPL's own second line of defence.
    proc = sandbox.run([sys.executable, "probe.py", str(home), str(qa)], cwd=repo,
                       writable=[repo, home], policy=sandbox.Policy(qa_root=qa), timeout=60)
    seen = json.loads(proc.stdout)
    assert str(seen["ssh"]).startswith("denied") and str(seen["config_env_file"]).startswith("denied")


@MAC_BOX
def test_a_gate_named_for_the_network_keeps_it_and_nothing_else(tmp_path):
    home, qa = _home(tmp_path)
    repo = _repo(tmp_path)
    (repo / "probe.py").write_text(PROBE, encoding="utf-8")
    boxed = sandbox.run([sys.executable, "probe.py", str(home), str(qa)], cwd=repo,
                        writable=[repo], network=True, timeout=60)
    seen = json.loads(boxed.stdout)
    assert seen["tcp"] != "denied PermissionError"   # the network is the gate's
    assert str(seen["write_home"]).startswith("denied")


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_a_daemon_does_not_outlive_its_run(tmp_path):
    repo = _repo(tmp_path)
    pidfile = tmp_path / "daemon.pid"
    cmd = _script(repo, "import subprocess, sys\n"
                        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n")
    sandbox.run(cmd, cwd=repo, shell=True, writable=[repo, tmp_path], timeout=60)
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the daemon a run started was still alive after it returned")


def test_output_reads_as_text_mode_read_it(tmp_path):
    """`_call` writes the run's output to files, so it decodes them itself, as `text=True` did,
    with universal newlines. Without that, a Windows repro's `stdout_contains "[]\\nFalse"`
    never matched `[]\\r\\nFalse` (CI, 2026-11-04)."""
    repo = _repo(tmp_path)
    proc = sandbox.run([sys.executable, "-c",
                        "import sys; sys.stdout.buffer.write(b'a\\r\\nb\\rc\\n')"],
                       cwd=repo, writable=[repo], timeout=60)
    assert proc.stdout == "a\nb\nc\n"


def test_a_shell_gate_keeps_its_pipes(tmp_path):
    repo = _repo(tmp_path)
    proc = sandbox.run(f'"{sys.executable}" -c "print(41 + 1)" | {"findstr" if os.name == "nt" else "grep"} 4',
                       cwd=repo, shell=True, writable=[repo], timeout=60)
    assert proc.returncode == 0 and "42" in proc.stdout


# ── the profile and the runner ────────────────────────────────────────────

def test_the_profile_reads_the_box_and_a_typo_never_turns_it_off():
    notes = []
    got = profile.sandbox_from({"sandbox": "of", "sandbox_network": "install, build",
                                "sandbox_write": "~/.cache/uv", "test_env": "A,B"}, notes)
    assert got == {"mode": "auto", "network_gates": ["install", "build"],
                   "write": ["~/.cache/uv"], "env_names": ["A", "B"]}
    assert any("not understood" in n for n in notes)
    assert profile.sandbox_from({"sandbox": "required"}, [])["mode"] == "required"
    off_notes = []
    assert profile.sandbox_from({"sandbox": "off"}, off_notes)["mode"] == "off"
    assert any("caller's environment" in n for n in off_notes)
    assert all(k in profile.KNOWN for k in ("sandbox", "sandbox_network", "sandbox_write",
                                             "test_env"))


def test_facts_say_what_boxed_the_projects_code():
    fact = sandbox.Policy(mode="off").as_fact()
    assert fact["box"].startswith("off") and fact["environment"] == "caller's"
    auto = sandbox.Policy(network_gates=["install"], env_names=["A"], floor="auto").as_fact()
    assert auto["environment"] == "allowlisted" and auto["network_gates"] == ["install"]
    assert auto["floor"] == "auto"


def test_the_testers_bash_runs_in_claude_codes_sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "jobs").mkdir(parents=True)
    (home / ".config" / "gateway.env").write_text("K=1", encoding="utf-8")
    (home / ".config" / "jobs" / "bot.env").write_text("T=1", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    env = {"ANTHROPIC_API_KEY": "sk", "GH_TOKEN": "g", "PATH": "/bin", "DB_PWD": "x",
           "MIRROR": "https://u:p@host/simple", "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    flags = runner.tester_sandbox(repo, qa_root, env, "auto")
    assert flags[0] == "--settings"
    box = json.loads(flags[1])["sandbox"]
    assert box["enabled"] and box["allowUnsandboxedCommands"] is False
    # In bypass mode, the mode the runner starts the tester in, the sandbox's proxy lets an
    # unlisted host through unless the allowlist is strict (measured 2026-11-03).
    assert box["network"] == {"strictAllowlist": True, "allowedDomains": []}
    assert {e["name"] for e in box["credentials"]["envVars"]} == {"ANTHROPIC_API_KEY",
                                                                    "GH_TOKEN", "DB_PWD", "MIRROR"}
    assert os.path.realpath(str(qa_root)) in box["filesystem"]["allowWrite"]
    assert os.path.realpath(str(repo / ".git")) in box["filesystem"]["allowWrite"]
    deny = box["filesystem"]["denyRead"]
    assert "~/.ssh" in deny and os.path.realpath(str(tmp_path / "cfg")) in deny
    assert str(home / ".config" / "gateway.env") in deny
    assert str(home / ".config" / "jobs" / "bot.env") in deny
    for command in runner.HARNESS_COMMANDS:
        assert command in box["excludedCommands"] and f"{command} *" in box["excludedCommands"]
    assert box["failIfUnavailable"] is False
    assert json.loads(runner.tester_sandbox(repo, qa_root, env, "required")[1])[
        "sandbox"]["failIfUnavailable"] is True
    assert runner.tester_sandbox(repo, qa_root, env, "off") == []


ARGV_STUB = ("import json, os, sys\nfrom pathlib import Path\n"
             "Path(os.environ['ARGV_OUT']).write_text(json.dumps(sys.argv))\nprint('stub ran')\n")


def test_verdict_run_launches_the_tester_with_the_sandbox_settings(tmp_path):
    from test_runner import write_stub
    from test_sweep import RUNNER, project
    repo, home, qa = project(tmp_path)
    launcher = write_stub(tmp_path, ARGV_STUB, name="claude-argv")
    out = tmp_path / "argv.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env.update(VERDICT_HOME=str(home), ARGV_OUT=str(out))
    subprocess.run([sys.executable, str(RUNNER), "--repo", str(repo), "--claude-cmd",
                    str(launcher), "--model", "opus", "--no-provision", "--no-premeasure",
                    "--env-passthrough", "ARGV_OUT"], capture_output=True, text=True, env=env)
    argv = json.loads(out.read_text(encoding="utf-8"))
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["network"]["strictAllowlist"] is True


# ── the configuration a checkout carries for the tester's session ───────────────────

def test_the_claude_configuration_a_repository_tracks_is_found_whatever_its_case(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    (repo / ".claude" / "agents" / "verdict.md").write_text("not the contract\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "ship claude config"], repo)
    # Written on this machine, untracked: the operator's, never the repository's authors'.
    (repo / ".claude" / "settings.local.json").write_text('{"hooks": {}}', encoding="utf-8")
    tracked, why = runner.repo_claude_config(repo)
    assert why is None and tracked == [".claude/agents/verdict.md", ".claude/settings.json"]
    other = _repo(tmp_path, "other")
    (other / ".CLAUDE").mkdir()
    (other / ".CLAUDE" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    git(["add", "-A"], other)
    git(["commit", "-qm", "upper case"], other)
    assert runner.repo_claude_config(other)[0] == [".CLAUDE/settings.json"]


@pytest.mark.skipif(os.name == "nt", reason="a symlink needs privileges on Windows")
def test_required_refuses_a_checkout_with_any_claude_configuration_but_verdicts_own(tmp_path):
    repo = _repo(tmp_path)
    assert runner.shipped_config_allowed(repo, "required")
    (repo / "cfg").mkdir()
    (repo / "cfg" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    os.symlink(repo / "cfg", repo / ".claude")                   # a symlink, untracked
    assert not runner.shipped_config_allowed(repo, "required")
    assert runner.shipped_config_allowed(repo, "auto")            # named only when tracked
    os.unlink(repo / ".claude")
    dot = repo / ".claude"
    (dot / "agents").mkdir(parents=True)
    agent, hooks = "the contract\n", {"PreToolUse": []}
    (dot / "agents" / "verdict.md").write_text(agent, encoding="utf-8")
    (dot / "settings.local.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    (dot / runner.PROVISION_RECORD).write_text(json.dumps({
        "agent": {"sha256": runner._sha(agent)},
        "hooks": {"sha256": runner._sha(json.dumps(hooks, sort_keys=True))}}), encoding="utf-8")
    assert runner.shipped_config_allowed(repo, "required")       # provision's own, unchanged
    (dot / "agents" / "verdict.md").write_text("planted\n", encoding="utf-8")
    assert not runner.shipped_config_allowed(repo, "required", stage="after premeasure")


def test_required_fails_closed_when_git_cannot_say(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(runner, "repo_claude_config", lambda r: ([], "fatal: not a git repository"))
    assert not runner.shipped_config_allowed(repo, "required")


def test_required_refuses_a_repository_that_ships_claude_hooks_and_auto_names_them(tmp_path):
    """Measured 2026-11-03: a tracked `.claude/settings.json` SessionStart hook ran in a session
    started with `--setting-sources project,local` — before the tester's first turn, outside the
    Bash sandbox — and saw `ANTHROPIC_API_KEY`."""
    from test_sweep import project, run as run_runner
    repo, home, qa = project(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "ship a hook"], repo)
    proc, ran = run_runner(tmp_path, repo, home)
    assert ran and "ships .claude/settings.json" in proc.stderr
    (tmp_path / "argv.json").unlink()        # the stub's mark from the run above
    proc, ran = run_runner(tmp_path, repo, home, "--sandbox", "required")
    assert proc.returncode == 2 and not ran, proc.stderr
    assert "nothing was started" in proc.stderr


def test_a_shipped_profile_cannot_turn_the_box_off_under_a_floor(tmp_path):
    """Review 2026-11-03: a repository that ships `.qa/` is its own QA root, and its
    `profile.md` said `sandbox: off` and `test_env: ANTHROPIC_API_KEY` — both took."""
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text("---\nsandbox: off\ntest_env: ANTHROPIC_API_KEY\n"
                                   "sandbox_write: ~\n---\n", encoding="utf-8")
    notes = []
    pol = sandbox.policy_from(profile.sandbox_from(profile.load(qa)[0], notes), qa, notes,
                              floor="required")
    assert pol.mode == "required" and not pol.env_names and not pol.write
