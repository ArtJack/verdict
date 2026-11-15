"""The browser pass: a website measured in a real browser, GET only, no model.

Two halves. The first needs no browser: the `site:` block, the routing that names a page's
source file, image headers, the no-JavaScript form reading, the finding's shape and identity,
resolution by measurement, and the network rule every request goes through. The second drives
Chrome over a small site with one seeded defect per check and a clean twin beside each
(`browser_site.py`), and runs only where Playwright and a browser are installed.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verdict_mcp import browser  # noqa: E402
from verdict_mcp.harness import finding_hash  # noqa: E402
from verdict_mcp.profile import parse as parse_profile  # noqa: E402
from verdict_mcp.validate import validate_finding  # noqa: E402

import browser_site  # noqa: E402


# ── the site: block ───────────────────────────────────────────────────────────

def _profile(block: str) -> dict:
    return parse_profile(f"---\n{block}---\n\n# QA Profile\n")


def test_no_site_block_is_no_browser_pass():
    assert browser.site_from(_profile("gates:\n  suite: pytest\n")) is None


def test_a_site_block_reads_into_a_site():
    site = browser.site_from(_profile(
        "site:\n  url: https://example.com/\n  pages: /contact /pay\n  max_pages: 9\n"
        "  checks: links, get-form\n  skip: /admin\n"))
    assert site.url == "https://example.com/"
    assert site.pages == ["https://example.com/contact", "https://example.com/pay"]
    assert site.max_pages == 9 and site.checks == ("links", "get-form") and site.skip == ["/admin"]
    assert not site.loopback


def test_port_is_one_free_port_in_both_the_url_and_the_start_command():
    site = browser.site_from(_profile(
        "site:\n  url: http://127.0.0.1:{port}/\n  start: npx next start -p {port}\n"))
    port = site.url.rsplit(":", 1)[1].strip("/")
    assert port.isdigit() and site.start == f"npx next start -p {port}" and site.loopback


@pytest.mark.parametrize("block, words", [
    ("site:\n  start: npm start\n", "needs a `url`"),
    ("site:\n  url: ftp://example.com/\n", "http(s)"),
    ("site:\n  url: https://example.com/\n  start: npm start\n", "must be on it"),
    ("site:\n  url: https://example.com/\n  colour: blue\n", "unknown key"),
    ("site:\n  url: https://example.com/\n  checks: links, vibes\n", "unknown check"),
    ("site:\n  url: https://example.com/\n  max_pages: many\n", "whole number"),
    ("site:\n  url: https://example.com/\n  pages: https://elsewhere.org/x\n", "not on the site"),
    ("site: https://example.com/\n", "block"),
])
def test_a_site_block_that_cannot_run_is_an_error_naming_why(block, words):
    with pytest.raises(browser.SiteError, match=r"(?i)" + __import__("re").escape(words)):
        browser.site_from(_profile(block))


def test_the_profile_reads_site_as_a_known_key(tmp_path):
    from verdict_mcp.profile import load
    (tmp_path / "profile.md").write_text("---\nsite:\n  url: https://example.com/\n---\n",
                                         encoding="utf-8")
    config, notes = load(tmp_path)
    assert config["site"] == {"url": "https://example.com/"}
    assert not any("site" in n for n in notes)


# ── the page's source file ────────────────────────────────────────────────────

def _touch(root: Path, *paths: str) -> None:
    for rel in paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")


def test_next_app_router_pages_resolve_through_groups_dynamics_and_catch_alls(tmp_path):
    _touch(tmp_path, "src/app/page.tsx", "src/app/(marketing)/about/page.tsx",
           "src/app/blog/[slug]/page.tsx", "src/app/docs/[...path]/page.mdx",
           "src/app/blog/featured/page.tsx")
    assert browser.source_of(tmp_path, "/") == "src/app/page.tsx"
    assert browser.source_of(tmp_path, "/about") == "src/app/(marketing)/about/page.tsx"
    assert browser.source_of(tmp_path, "/blog/featured") == "src/app/blog/featured/page.tsx"
    assert browser.source_of(tmp_path, "/blog/hello-world") == "src/app/blog/[slug]/page.tsx"
    assert browser.source_of(tmp_path, "/docs/a/b/c") == "src/app/docs/[...path]/page.mdx"
    assert browser.source_of(tmp_path, "/nowhere/at/all") is None


def test_pages_router_and_static_files_resolve(tmp_path):
    _touch(tmp_path, "pages/index.tsx", "pages/a/b.tsx", "pages/post/[id].tsx")
    assert browser.source_of(tmp_path, "/") == "pages/index.tsx"
    assert browser.source_of(tmp_path, "/a/b") == "pages/a/b.tsx"
    assert browser.source_of(tmp_path, "/post/42") == "pages/post/[id].tsx"
    static = tmp_path / "static-site"
    _touch(static, "index.html", "about.html", "guide/index.html")
    assert browser.source_of(static, "/") == "index.html"
    assert browser.source_of(static, "/about") == "about.html"
    assert browser.source_of(static, "/about.html") == "about.html"
    assert browser.source_of(static, "/guide/") == "guide/index.html"
    assert browser.source_of(None, "/") is None


# ── image headers ─────────────────────────────────────────────────────────────

def test_image_sizes_are_read_from_png_gif_jpeg_and_webp_headers():
    assert browser.image_size(browser_site.png(100, 50)) == (100, 50)
    assert browser.image_size(b"GIF89a" + struct.pack("<HH", 32, 16) + b"\x00" * 8) == (32, 16)
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 630, 1200) + b"\x00" * 10
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"\x00" * 14 + sof
    assert browser.image_size(jpeg) == (1200, 630)
    vp8x = (b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8
            + (1586 - 1).to_bytes(3, "little") + (992 - 1).to_bytes(3, "little"))
    assert browser.image_size(vp8x) == (1586, 992)
    assert browser.image_size(b"<svg/>") is None
    assert browser.image_size(b"\xff\xd8\x00") is None


# ── forms without JavaScript ──────────────────────────────────────────────────

def test_a_get_form_with_personal_fields_is_read_and_a_search_form_is_not():
    html = ('<form role="search"><input name="q"></form>'
            '<form action="/find"><input name="q"></form>'
            '<form><input type="search" name="anything"></form>'
            '<form><input name="email" type="email"><textarea name="message"></textarea></form>'
            '<form method="post"><input name="email"></form>'
            '<form method="GET"><input type="password" name="pw"><input name="user"></form>'
            '<form><input name="colour"></form>')
    forms = browser.get_forms(html)
    assert [f["fields"] for f in forms] == [["email", "message"], ["pw"]]
    assert [f["secret"] for f in forms] == [False, True]


# ── the finding ───────────────────────────────────────────────────────────────

def _entry(**over):
    entry = browser.finding("autofill-trap", "/contact", "src/app/contact/page.tsx",
                            "Autofill fills a field nobody can see: `company` on /contact",
                            "Major", "P1", ["on /contact, autofill wrote 'x' into input[name=company]"],
                            "mechanism", "narrative", "Chrome 157.0.1.2 (headless)",
                            also=over.pop("also", None))
    entry.update(over)
    return entry


def test_a_browser_finding_is_validator_clean_and_cites_its_source_file_first():
    entry = _entry(id="T-1")
    assert validate_finding(entry, "findings/T-1.json", set()) == []
    assert entry["evidence"][0].startswith("src/app/contact/page.tsx — ")
    assert entry["confidence"] == "proven" and entry["failure_classification"] is None
    # The identity is the source file and the title: the browser's version, which moves with
    # every Chrome update, is not part of it.
    other = _entry(id="T-2")
    other["evidence"][-1] = browser.marker("autofill-trap", "/contact", "Chrome 999.0 (headless)")
    assert finding_hash(entry) == finding_hash(other)


def test_marks_round_trip_for_every_page_a_finding_was_measured_on():
    entry = _entry(also=["/about", "/contact"])
    assert browser.marks_of(entry) == {("autofill-trap", "/contact"), ("autofill-trap", "/about")}
    assert browser.marks_of({"evidence": ["src/x.py:3 — returns None"]}) == set()


def _prior(*findings):
    return {"findings": list(findings)}


def test_a_finding_measured_again_everywhere_and_not_found_is_resolved():
    gone = dict(_entry(also=["/about"]), id="T-1")
    assert browser.resolved_by_measurement(
        _prior(gone), {("autofill-trap", "/contact"), ("autofill-trap", "/about")}, set()) == ["T-1"]


def test_a_finding_is_left_open_when_any_page_was_not_measured_or_it_was_found_again():
    entry = dict(_entry(also=["/about"]), id="T-1")
    only_one = {("autofill-trap", "/contact")}
    both = only_one | {("autofill-trap", "/about")}
    assert browser.resolved_by_measurement(_prior(entry), only_one, set()) == []
    assert browser.resolved_by_measurement(_prior(entry), both, {"T-1"}) == []
    assert browser.resolved_by_measurement(_prior(dict(entry, status="accepted")), both, set()) == []
    model_read = {"id": "T-2", "status": "open", "evidence": ["src/x.py:3 — returns None"]}
    assert browser.resolved_by_measurement(_prior(model_read), both, set()) == []


def test_a_path_the_routing_files_mention_is_named(tmp_path):
    (tmp_path / "next.config.ts").write_text('rewrites: [{ source: "/lab/brain" }]',
                                             encoding="utf-8")
    assert browser.configured(tmp_path, "/lab/brain") == "next.config.ts"
    assert browser.configured(tmp_path, "/contact") is None
    assert browser.configured(tmp_path, "/") is None
    assert browser.configured(None, "/lab/brain") is None


# ── the network rule ──────────────────────────────────────────────────────────

class _Route:
    def __init__(self):
        self.did = None

    def abort(self):
        self.did = "abort"

    def continue_(self):
        self.did = "continue"


def _guard_run():
    site = browser.make_site("https://example.com/")
    return browser._Run(site, None, lambda m: None, browser=None, engine="test")


@pytest.mark.parametrize("method, url, expected", [
    ("GET", "https://example.com/about", "continue"),
    ("HEAD", "https://example.com/about", "continue"),
    ("POST", "https://example.com/api/contact", "abort"),
    ("PUT", "https://example.com/api/x", "abort"),
    ("DELETE", "https://example.com/api/x", "abort"),
    ("PATCH", "https://example.com/api/x", "abort"),
    ("GET", "https://www.google-analytics.com/collect", "abort"),
    ("GET", "https://example.com.evil.org/x", "abort"),
    ("GET", "http://example.com/about", "abort"),
    ("GET", "data:image/png;base64,AAAA", "continue"),
])
def test_every_request_is_a_get_to_the_site_or_it_is_aborted(method, url, expected):
    run, route = _guard_run(), _Route()
    run.guard(route, SimpleNamespace(url=url, method=method))
    assert route.did == expected
    if method not in browser.NOT_A_WRITE and url.startswith("https://example.com/"):
        assert run.writes == [f"{method} {url.split('example.com', 1)[1]}"]


def test_links_that_read_like_actions_are_never_requested():
    run = _guard_run()
    for path in ("/logout", "/account/sign-out", "/items/4/delete", "/unsubscribe?id=1",
                 "/subscription/cancel"):
        assert run.allowed("https://example.com" + path), path
    for path in ("/blog/how-to-cancel-a-meeting-politely", "/deleted-scenes", "/pricing"):
        assert run.allowed("https://example.com" + path) is None, path


def test_without_playwright_the_pass_says_so_and_measures_nothing(monkeypatch, capsys):
    monkeypatch.setattr(browser, "sync_playwright", None)
    result = browser.browse(browser.make_site("https://example.com/"))
    assert result.findings == [] and result.measured == set()
    assert result.not_tested == [browser.NO_PLAYWRIGHT]
    assert browser.main(["https://example.com/"]) == 3
    assert browser.main(["ftp://example.com/"]) == 2


# ── in a real browser ─────────────────────────────────────────────────────────

def _browser_available() -> str | None:
    if browser.sync_playwright is None:
        return "Playwright is not installed"
    try:
        with browser.sync_playwright() as pw:
            found, why = browser._launch(pw)
            if found is None:
                return f"no browser: {why}"
            found.close()
    except Exception as exc:  # noqa: BLE001 - any failure here means "cannot run here"
        return f"no browser: {exc}"
    return None


_NO_BROWSER = _browser_available()
needs_browser = pytest.mark.skipif(_NO_BROWSER is not None, reason=str(_NO_BROWSER))


@pytest.fixture(scope="module")
def site_run(tmp_path_factory):
    """One pass over the seeded site, shared by the tests below (it takes a minute or two)."""
    root = browser_site.build(tmp_path_factory.mktemp("site"))
    with browser_site.serve(root) as (base, log):
        site = browser.make_site(base + "/index.html", budget_s=600)
        result = browser.browse(site, repo=root, log=lambda m: None)
        yield result, list(log)


def _found(result) -> dict:
    out: dict = {}
    for f in result.findings:
        for check, path in browser.marks_of(f):
            out.setdefault(check, set()).add(path)
    return out


@needs_browser
@pytest.mark.parametrize("check", sorted(browser_site.SEEDED))
def test_each_seeded_defect_is_found_on_its_page(site_run, check):
    result, _log = site_run
    if check == "autofill-trap" and "Chrome " not in result.facts.get("browser", ""):
        pytest.skip("the autofill check needs Google Chrome's autofill")
    assert set(browser_site.SEEDED[check]) <= _found(result).get(check, set())


@needs_browser
def test_no_clean_twin_is_flagged(site_run):
    result, _log = site_run
    flagged = {(c, p) for c, pages in _found(result).items() for p in pages}
    seeded = {(c, p) for c, pages in browser_site.SEEDED.items() for p in pages}
    assert flagged - seeded == set()


@needs_browser
def test_no_write_reached_the_server_and_no_action_link_was_followed(site_run):
    result, log = site_run
    assert [m for m, _p in log if m not in ("GET", "HEAD")] == []
    assert not [p for _m, p in log if "logout" in p]
    assert "POST /api/track" in result.facts["writes_blocked"]
    assert set(result.facts["third_party_blocked"]) == {"third-party.invalid"}
    assert any("never requested: /logout" in line for line in result.not_tested)


@needs_browser
def test_every_finding_is_a_validator_clean_measurement(site_run):
    result, _log = site_run
    for n, entry in enumerate(result.findings, 1):
        assert validate_finding(dict(entry, id=f"B-{n}"), f"findings/B-{n}.json", set()) == []
        assert any("not by a model" in e for e in entry["evidence"])
        assert entry["evidence"][0].split(" — ", 1)[0].endswith(".html"), entry["evidence"][0]


@needs_browser
def test_verdict_browse_writes_its_result_and_exits_zero(tmp_path, capsys):
    root = browser_site.build(tmp_path / "site")
    out = tmp_path / "out.json"
    with browser_site.serve(root) as (base, _log):
        code = browser.main([base + "/wide.html", "--only", "phone-width", "--max-pages", "1",
                             "--repo", str(root), "--json", str(out)])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [f["title"] for f in data["findings"]] == [
        "The page scrolls sideways on a phone: /wide.html"]
    assert "model calls: 0" in capsys.readouterr().out


# ── through verdict-local ─────────────────────────────────────────────────────

@needs_browser
def test_verdict_local_files_a_browser_finding_carries_it_unmeasured_and_resolves_it_measured(
        tmp_path):
    """The profile's `site:` block, end to end: run 1 files what the browser measured; run 2
    cannot reach the site, so the finding stays open and the report says why; run 3 measures
    the fixed page and resolves it — the one path to `resolved` this engine has, measurement."""
    from test_local_delta import ScriptedModel, state_of
    from test_local_gate import GATE, branch_repo
    from verdict_mcp import small

    repo, _range = branch_repo(tmp_path)
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(browser_site.page("Home", '<a href="wide.html">Rates</a>'),
                                     encoding="utf-8")
    (root / "wide.html").write_text(browser_site.PAGES["wide.html"], encoding="utf-8")
    qa = tmp_path / "qa"
    qa.mkdir()

    def profile(url):
        (qa / "profile.md").write_text(
            f"---\ngates:\n  suite: {GATE}\nsite:\n  url: {url}\n  checks: phone-width\n"
            "  ready_s: 3\n---\n\n# QA Profile — sitey\n", encoding="utf-8")

    def run():
        return small.run(repo, qa, ScriptedModel(), limit=2, gate=None, reruns=0, prove=False)

    with browser_site.serve(root) as (base, _log):
        profile(base + "/index.html")
        assert run() == 0
    wide = [f for f in state_of(qa)["findings"]
            if f["title"] == "The page scrolls sideways on a phone: /wide.html"]
    assert len(wide) == 1 and wide[0]["status"] == "open" and wide[0]["confidence"] == "proven"
    fid = wide[0]["id"]

    profile("http://127.0.0.1:9/index.html")            # nothing listens there
    assert run() == 0
    down = state_of(qa)
    assert next(f for f in down["findings"] if f["id"] == fid)["status"] == "open"
    assert any("no page was checked in a browser" in line
               for line in json.dumps(down).split('"') if line)

    (root / "wide.html").write_text(browser_site.PAGES["narrow.html"], encoding="utf-8")
    with browser_site.serve(root) as (base, _log):
        profile(base + "/index.html")
        assert run() == 0
    fixed = state_of(qa)
    assert next(f for f in fixed["findings"] if f["id"] == fid)["status"] == "resolved"
    assert fid in json.dumps(fixed)


def test_verdict_local_mints_carries_and_resolves_what_the_browser_measured(tmp_path,
                                                                            monkeypatch):
    """The same wiring with the browser replaced by its results, so it runs everywhere: a
    finding the pass measured is filed; a pass that measured nothing leaves it open; a pass
    that measured the page again and found nothing resolves it."""
    from test_local_delta import ScriptedModel, state_of
    from test_local_gate import GATE, branch_repo
    from verdict_mcp import small

    repo, _range = branch_repo(tmp_path)
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {GATE}\nsite:\n  url: https://example.com/\n---\n\n"
        "# QA Profile — sitey\n", encoding="utf-8")
    entry = browser.finding("phone-width", "/rates", None,
                            "The page scrolls sideways on a phone: /rates", "Major", "P1",
                            ["on /rates at 375×812 the page can be scrolled 265 px sideways"],
                            "mechanism", "narrative", "Chrome test")
    page = {"pages": [{"path": "/rates", "status": 200}], "browser": "Chrome test"}
    passes = [browser.Pass(findings=[entry], facts=page, measured={("phone-width", "/rates")}),
              browser.Pass(not_tested=["no page was checked in a browser: it did not answer"],
                           facts={"skipped": "it did not answer"}),
              browser.Pass(facts=page, measured={("phone-width", "/rates")})]
    monkeypatch.setattr(browser, "browse", lambda site, **kwargs: passes.pop(0))

    def run():
        return small.run(repo, qa, ScriptedModel(), limit=2, gate=None, reruns=0, prove=False)

    assert run() == 0
    filed = [f for f in state_of(qa)["findings"] if f["title"] == entry["title"]]
    assert len(filed) == 1 and filed[0]["status"] == "open"
    fid = filed[0]["id"]
    assert run() == 0
    down = state_of(qa)
    assert next(f for f in down["findings"] if f["id"] == fid)["status"] == "open"
    assert "browser pass: no page was checked in a browser" in json.dumps(down)
    assert run() == 0
    assert next(f for f in state_of(qa)["findings"] if f["id"] == fid)["status"] == "resolved"
    assert passes == []
