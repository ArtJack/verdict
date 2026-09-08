"""Which account pays, and which endpoint answers.

A nightly should be able to spend a chosen subscription, or a local model server,
without the credential appearing in a crontab or a log — and without the silent
failure that cost an afternoon: a config directory the CLI has never seen has
accepted neither the trust dialog nor bypass-permissions mode, so a headless run
there exits 0 having done nothing, which the gate reports as a lost run while the
cause is configuration.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import runner  # noqa: E402


def test_read_env_file_skips_comments_and_strips_quotes(tmp_path):
    path = tmp_path / "env"
    path.write_text('# a comment\n\nCLAUDE_CONFIG_DIR="/tmp/cfg"\n'
                    "ANTHROPIC_BASE_URL='http://gw:4000'\nnot a pair\n", encoding="utf-8")
    assert runner.read_env_file(path) == {"CLAUDE_CONFIG_DIR": "/tmp/cfg",
                                          "ANTHROPIC_BASE_URL": "http://gw:4000"}


def test_seed_config_marks_the_repo_trusted_and_keeps_what_is_there(tmp_path):
    cfg, repo = tmp_path / "cfg", tmp_path / "repo"
    repo.mkdir()
    cfg.mkdir()
    (cfg / ".claude.json").write_text(json.dumps({"userID": "u1", "projects": {"/other": {}}}),
                                      encoding="utf-8")
    runner.seed_config(cfg, repo)
    doc = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert doc["bypassPermissionsModeAccepted"] is True
    assert doc["projects"][str(repo.resolve())]["hasTrustDialogAccepted"] is True
    assert doc["userID"] == "u1" and "/other" in doc["projects"], "an existing config survives"


def test_seed_config_creates_the_directory_and_survives_a_broken_file(tmp_path):
    cfg, repo = tmp_path / "new" / "cfg", tmp_path / "repo"
    repo.mkdir()
    runner.seed_config(cfg, repo)
    assert (cfg / ".claude.json").is_file()
    (cfg / ".claude.json").write_text("{not json", encoding="utf-8")
    runner.seed_config(cfg, repo)
    doc = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert doc["bypassPermissionsModeAccepted"] is True


def test_a_named_account_is_seeded_and_named(tmp_path):
    cfg, repo = tmp_path / "cfg", tmp_path / "repo"
    repo.mkdir()
    env, notes = runner.session_env({"CLAUDE_CONFIG_DIR": str(cfg)}, repo)
    assert (cfg / ".claude.json").is_file(), "the run must not be refused in silence"
    assert any("CLAUDE_CONFIG_DIR" in n and "trust seeded" in n for n in notes), notes
    assert "ANTHROPIC_API_KEY" not in env, "a subscription run carries no api key"


def test_a_gateway_gets_the_three_flags_and_the_token_as_api_key(tmp_path):
    cfg, repo = tmp_path / "cfg", tmp_path / "repo"
    repo.mkdir()
    env, notes = runner.session_env(
        {"ANTHROPIC_BASE_URL": "http://gw:4000", "ANTHROPIC_AUTH_TOKEN": "sk-x",
         "CLAUDE_CONFIG_DIR": str(cfg)}, repo)
    assert env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] == "1"
    assert env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"
    assert env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
    assert env["ANTHROPIC_API_KEY"] == "sk-x"
    assert any("http://gw:4000" in n for n in notes)


def test_an_operators_own_flag_value_is_never_overwritten(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env, _ = runner.session_env(
        {"ANTHROPIC_BASE_URL": "http://gw:4000", "ANTHROPIC_AUTH_TOKEN": "sk-x",
         "ANTHROPIC_API_KEY": "sk-mine",
         "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "0"}, repo)
    assert env["ANTHROPIC_API_KEY"] == "sk-mine"
    assert env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] == "0"


def test_a_gateway_without_an_isolated_config_is_warned_about(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _, notes = runner.session_env({"ANTHROPIC_BASE_URL": "http://gw:4000"}, repo)
    assert any("401" in n for n in notes), \
        "the CLI prefers its stored login and the gateway rejects it — say so before the run"


def test_the_ambient_login_is_left_alone(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env, notes = runner.session_env({"PATH": "/usr/bin"}, repo)
    assert env == {"PATH": "/usr/bin"} and notes == []


def test_the_runner_refuses_a_missing_env_file(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    code = runner.main(["t", "--repo", str(repo), "--env-file", str(tmp_path / "nope"),
                        "--claude-cmd", "/bin/echo", "--no-provision"])
    assert code == 2 and "does not exist" in capsys.readouterr().err


def test_the_env_file_reaches_the_child_and_seeds_its_config(tmp_path, monkeypatch):
    repo, home, cfg = tmp_path / "repo", tmp_path / "home", tmp_path / "cfg"
    repo.mkdir()
    monkeypatch.setenv("VERDICT_HOME", str(home))
    (home / "t").mkdir(parents=True)
    (home / "t" / "profile.md").write_text(
        f"---\ngates: {{}}\n---\n\n# QA Profile — t\n\nProject-Key: t\nRepo-Path: {repo}\n"
        "Security-Pass: disabled\nSchema-Version: 1\n", encoding="utf-8")
    env_file = tmp_path / "run.env"
    env_file.write_text(f"CLAUDE_CONFIG_DIR={cfg}\n", encoding="utf-8")

    seen = {}

    def fake_stream(cmd, cwd, env, timeout_s):
        seen.update(env)
        return 0, ""

    monkeypatch.setattr(runner, "_run_streaming", fake_stream)
    runner.main(["t", "--repo", str(repo), "--env-file", str(env_file),
                 "--claude-cmd", "/bin/echo", "--no-provision"])
    assert seen.get("CLAUDE_CONFIG_DIR") == str(cfg), "the child spends the named account"
    assert seen.get("VERDICT_STRICT") == "1", "the guards stay armed"
    doc = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert doc["projects"][str(repo.resolve())]["hasTrustDialogAccepted"] is True
