"""The site the browser pass checks, as the profile's `site:` block says it: the checks, the
limits, the origins and paths it never touches, and the Site and Pass the rest of the pass uses.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import re
import socket
import urllib.robotparser
from dataclasses import dataclass, field


# ── configuration ─────────────────────────────────────────────────────────────


CHECKS = ("autofill-trap", "phone-width", "long-input", "ios-zoom", "hidden-at-load",
          "focus-visible", "keyboard", "get-form", "social-image", "links")


DESKTOP = {"width": 1280, "height": 800}


PHONE = {"width": 375, "height": 812}


MAX_PAGES = 25


READY_S = 90


BUDGET_S = 600


NAV_TIMEOUT_MS = 30_000


SETTLE_MS = 400


FOCUS_STOPS_PER_PAGE = 25


FOCUS_STOPS = 150


KEY_CANDIDATES_PER_PAGE = 4


KEY_CANDIDATES = 12


LINK_CHECKS = 40


LONG_NAME = 120


HIDDEN_SHARE = 0.25          # of the page's text, hidden at load, to be worth a finding


HIDDEN_MAJOR = 0.5


REVEALED_SHARE = 0.6         # of what was hidden, shown by scrolling: a reveal, not a closed menu


MIN_TEXT = 200


ENGINE = "verdict-browse"


NO_PLAYWRIGHT = ("the profile names a site, and no browser could be driven: Playwright is not "
                 "installed (pip install 'verdict-qa-mcp[browser]'; the installed Google Chrome "
                 "is used when there is one)")


NOT_A_WRITE = ("GET", "HEAD", "OPTIONS")


# A link whose path says it changes state is never followed, even on a GET.
STATEFUL_PATH = re.compile(r"(?:^|/)(?:log-?out|sign-?out|log-?off|delete|remove|destroy|"
                           r"unsubscribe|cancel|revoke|reset)(?:[/?#.]|$)", re.I)


ASSET_SUFFIX = re.compile(r"\.(?:pdf|png|jpe?g|gif|webp|avif|svg|ico|css|js|mjs|map|json|xml|txt|"
                          r"csv|xlsx?|docx?|pptx?|zip|gz|tgz|mp3|mp4|webm|mov|woff2?|ttf|otf|"
                          r"rss|atom|webmanifest)$", re.I)


BOT_WALL = re.compile(r"cf-chl|challenge-platform|just a moment|attention required|"
                      r"verifying you are human|captcha-delivery|datadome|perimeterx|px-captcha|"
                      r"security checkpoint", re.I)


LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")


# Served by the hosting platform, never by the app: a local server answers 404 for all of them.
PLATFORM_PATHS = ("/_vercel/", "/.netlify/", "/cdn-cgi/", "/.well-known/vercel/")


# Where a site's redirects and rewrites live. A local run has none of the deployment's settings,
# so a path these files mention may be served in production and missing here (measured
# 2026-11-14: artjeck.com's /lab/brain is a rewrite that exists only when an env var is set).
ROUTING_FILES = ("next.config.js", "next.config.mjs", "next.config.cjs", "next.config.ts",
                 "vercel.json", "netlify.toml", "_redirects", "public/_redirects",
                 "nuxt.config.ts", "nuxt.config.js", "astro.config.mjs", "astro.config.ts",
                 "svelte.config.js", "firebase.json", "staticwebapp.config.json")


_MARK = re.compile(r"measured by the browser check `([\w-]+)` on `([^`]+)`")


# Chrome's own field types, as the DevTools protocol's Autofill.trigger takes them. The values
# are synthetic: no person's data is ever typed into a page.
ADDRESS = {"fields": [{"name": n, "value": v} for n, v in (
    ("NAME_FULL", "Pat Example"), ("NAME_FIRST", "Pat"), ("NAME_LAST", "Example"),
    ("COMPANY_NAME", "Example Test Co"), ("EMAIL_ADDRESS", "pat@example.com"),
    ("PHONE_HOME_WHOLE_NUMBER", "5555550100"), ("ADDRESS_HOME_LINE1", "1 Example Street"),
    ("ADDRESS_HOME_CITY", "Springfield"), ("ADDRESS_HOME_STATE", "CA"),
    ("ADDRESS_HOME_ZIP", "95814"), ("ADDRESS_HOME_COUNTRY", "US"))]}


class SiteError(ValueError):
    """A `site:` block, or a `verdict-browse` call, that cannot be run as written."""


@dataclass
class Site:
    url: str
    start: str | None = None
    pages: list = field(default_factory=list)
    max_pages: int = MAX_PAGES
    ready_s: int = READY_S
    budget_s: int = BUDGET_S
    checks: tuple = CHECKS
    skip: list = field(default_factory=list)

    @property
    def origin(self) -> str:
        return origin_of(self.url)

    @property
    def loopback(self) -> bool:
        return (urllib.parse.urlsplit(self.url).hostname or "") in LOOPBACK


@dataclass
class Pass:
    """What one browser pass found, could not do, and measured."""
    findings: list = field(default_factory=list)
    not_tested: list = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    measured: set = field(default_factory=set)      # {(check, page path)} that ran to the end


def _int(raw: dict, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key)
    if value in (None, ""):
        return default
    try:
        number = int(str(value).strip())
    except ValueError:
        raise SiteError(f"profile `site.{key}` must be a whole number, not {value!r}") from None
    if not low <= number <= high:
        raise SiteError(f"profile `site.{key}` must be between {low} and {high}, not {number}")
    return number


def _list(value) -> list:
    if value in (None, ""):
        return []
    return [x for x in re.split(r"[,\s]+", str(value).strip()) if x]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def origin_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def make_site(url: str, start: str | None = None, pages=(), max_pages: int = MAX_PAGES,
              ready_s: int = READY_S, budget_s: int = BUDGET_S, checks=None, skip=()) -> Site:
    """One validated site. `{port}` in the URL or the start command is a free port, the same
    one in both, so two runs at once do not collide."""
    if not url:
        raise SiteError("a site needs a `url`")
    if "{port}" in url or (start and "{port}" in start):
        port = str(free_port())
        url = url.replace("{port}", port)
        start = start.replace("{port}", port) if start else start
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SiteError(f"the site's url must be http(s) with a host, not {url!r}")
    if start and parts.hostname not in LOOPBACK:
        raise SiteError(f"`start` runs a server on this machine, so the url must be on it "
                        f"(127.0.0.1, localhost or ::1), not {parts.hostname!r}")
    chosen = tuple(checks) if checks else CHECKS
    unknown = [c for c in chosen if c not in CHECKS]
    if unknown:
        raise SiteError(f"unknown check(s) {', '.join(unknown)}; the checks are "
                        f"{', '.join(CHECKS)}")
    seeds = []
    for page in pages:
        page = str(page).strip()
        if not page:
            continue
        absolute = urllib.parse.urljoin(url, page)
        if origin_of(absolute) != origin_of(url):
            raise SiteError(f"page {page!r} is not on the site {origin_of(url)}")
        seeds.append(absolute)
    return Site(url=url, start=start or None, pages=seeds, max_pages=max_pages, ready_s=ready_s,
                budget_s=budget_s, checks=chosen, skip=[str(s) for s in skip if str(s)])


def site_from(config: dict) -> Site | None:
    """The profile's `site:` block, or None when there is none.

        site:
          url: http://127.0.0.1:{port}/
          start: npx next start -p {port}
          pages: /contact /pay
          max_pages: 25
    """
    raw = config.get("site")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SiteError("profile `site:` must be a block of `name: value` lines (url, start, "
                        f"pages, max_pages, ready_s, budget_s, checks, skip), not {raw!r}")
    unknown = sorted(k for k in raw if k not in ("url", "start", "pages", "max_pages", "ready_s",
                                                  "budget_s", "checks", "skip"))
    if unknown:
        raise SiteError(f"profile `site:` has unknown key(s) {', '.join(unknown)}")
    return make_site(str(raw.get("url") or ""), raw.get("start") or None, _list(raw.get("pages")),
                     max_pages=_int(raw, "max_pages", MAX_PAGES, 1, 500),
                     ready_s=_int(raw, "ready_s", READY_S, 1, 1800),
                     budget_s=_int(raw, "budget_s", BUDGET_S, 10, 7200),
                     checks=_list(raw.get("checks")) or None, skip=_list(raw.get("skip")))
