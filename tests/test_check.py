"""verdict-check (0.91.0): siblings and severity on the local tier, kept as leads."""

import json
import subprocess

from conftest import git
from verdict_mcp import check

SRC = """def refund(payment, amount=None):
    amount = amount or payment.total
    return amount


def capture(payment, amount=None):
    amount = amount or payment.total
    return amount


def total_of(payment):
    return payment.total
"""


class FakeModel:
    """The sibling question marks site 1 as the same defect and site 2 as not."""

    def __init__(self):
        self.calls = 0
        self.asked = []

    def ask_json(self, prompt, max_tokens=1200):
        self.calls += 1
        self.asked.append(prompt)
        if "SAME defect" in prompt:
            return {"sites": [{"id": 1, "same_defect": True, "why": "the same `or` swallows a zero amount"},
                              {"id": 2, "same_defect": False, "why": "reads the total, refunds nothing"}]}
        return None


def _repo(tmp_path):
    repo = tmp_path / "shop"
    (repo / "shop").mkdir(parents=True)
    (repo / "tests").mkdir()
    git(["init", "-qb", "main"], repo)
    (repo / "shop" / "pay.py").write_text(SRC, encoding="utf-8")
    (repo / "tests" / "test_pay.py").write_text("from shop.pay import refund\n# payment.total\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "shop"], repo)
    (repo / ".qa").mkdir()
    finding = {"id": "SHOP-F-1", "title": "`refund(amount=0)` refunds the whole `payment.total`", "severity": "Major",
               "priority": "P1", "status": "open", "confidence": "proven",
               "evidence": ["shop/pay.py:2 — `amount = amount or payment.total` turns 0 into the total"],
               "anchors": [{"path": "shop/pay.py", "line": 2}]}
    (repo / ".qa" / "state.json").write_text(json.dumps({
        "schema_version": 3, "project": "SHOP", "run_number": 4, "verdict": "pass with risks",
        "last_run": {"timestamp_utc": "2026-10-17T00:00:00Z", "git_sha": "x"}, "findings": [finding]}),
        encoding="utf-8")
    return repo, finding


def test_the_token_comes_from_the_cited_line_and_the_sites_from_a_search(tmp_path):
    repo, finding = _repo(tmp_path)
    assert check.tokens_of(finding, repo)[0] == "payment.total"
    sites = check.sites_of(repo, "payment.total", check._own_lines(finding))
    assert [(s["path"], s["line"]) for s in sites] == [("shop/pay.py", 7), ("shop/pay.py", 12)], \
        "the finding's own line and the tests are not siblings"
    assert "    7     amount = amount or payment.total" in sites[0]["excerpt"]


def test_leads_are_written_beside_the_state_never_into_it(tmp_path, capsys):
    repo, _ = _repo(tmp_path)
    before = (repo / ".qa" / "state.json").read_text(encoding="utf-8")
    model = FakeModel()
    assert check.main([str(repo)], _model=model) == 0
    assert model.calls == 1, "one question per finding: siblings"
    report = (repo / ".qa" / "reviews" / "4-local-check.md").read_text(encoding="utf-8")
    assert "sibling: `shop/pay.py:7` (`payment.total`) — the same `or` swallows a zero amount" in report
    assert "shop/pay.py:12" not in report
    (row,) = [json.loads(line) for line in (repo / ".qa" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["material"] == "yes" and row["siblings"] == 1 and "severity_notes" not in row
    assert row["kind"] == "local-check" and row["run"] == 4 and row["report"] == "reviews/4-local-check.md"
    assert (repo / ".qa" / "state.json").read_text(encoding="utf-8") == before
    assert "material: yes (SHOP-F-1)" in capsys.readouterr().err


def test_a_model_that_says_nothing_is_not_material_and_a_dry_run_asks_nothing(tmp_path, capsys):
    repo, _ = _repo(tmp_path)

    class Silent(FakeModel):
        def ask_json(self, prompt, max_tokens=1200):
            self.calls += 1
            return None

    assert check.main([str(repo)], _model=Silent()) == 0
    (row,) = [json.loads(line) for line in (repo / ".qa" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["material"] == "no"
    model = FakeModel()
    assert check.main([str(repo), "--dry-run"], _model=model) == 0 and model.calls == 0
    assert "SHOP-F-1: token payment.total · 2 site(s)" in capsys.readouterr().out


def test_no_gateway_is_said_and_nothing_is_written(tmp_path, capsys, monkeypatch):
    repo, _ = _repo(tmp_path)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert check.main([str(repo), "--env-file", str(tmp_path / "none.env")]) == 2
    assert "no gateway" in capsys.readouterr().err
    assert not (repo / ".qa" / "reviews.jsonl").exists()
    subprocess.run(["git", "-C", str(repo), "status"], check=True, capture_output=True)


def test_a_site_in_the_defects_own_function_or_next_to_another_site_is_not_a_sibling(tmp_path):
    repo, finding = _repo(tmp_path)
    (repo / "shop" / "pay.py").write_text(SRC.replace(
        "def refund(payment, amount=None):\n    amount = amount or payment.total\n",
        "def refund(payment, amount=None):\n    amount = amount or payment.total\n\n\n\n\n"
        "    assert amount <= payment.total\n"), encoding="utf-8")
    git(["commit", "-qam", "a second use inside refund"], repo)
    sites = check.sites_of(repo, "payment.total", check._own_lines(finding))
    assert [s["path"] + ":" + str(s["line"]) for s in sites] == ["shop/pay.py:12", "shop/pay.py:17"], \
        "line 7 sits inside refund itself; capture and total_of are other functions"


def test_a_module_level_citation_is_excluded_by_its_own_line(tmp_path):
    """The defect's own function covers a citation inside a function; a module-level one has no
    function to exclude, and only the nearby-line rule keeps it from being its own sibling."""
    repo = tmp_path / "conf"
    (repo / "shop").mkdir(parents=True)
    git(["init", "-qb", "main"], repo)
    (repo / "shop" / "conf.py").write_text(
        "FEE = settings.payment_fee\n" + "\n" * 8 + "LATE = settings.payment_fee + 1\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "conf"], repo)
    finding = {"anchors": [{"path": "shop/conf.py", "line": 1}]}
    sites = check.sites_of(repo, "settings.payment_fee", check._own_lines(finding))
    assert [(s["path"], s["line"]) for s in sites] == [("shop/conf.py", 10)]
