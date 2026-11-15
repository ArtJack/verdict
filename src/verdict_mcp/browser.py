#!/usr/bin/env python3
"""verdict-browse — a website in a real browser, measured, with no model in the room.

The local tier reads code one function at a time and asks a model what it thinks. On a website
that found little and claimed much: on 2026-11-11, two runs over a Next.js site made 11 claims and
none was true. The defect that mattered most that day was found in a browser instead: Chrome's
own autofill wrote a company name into an off-screen bot trap, and the server dropped every
message that came with it. No reading of the code alone showed that, because the code was
fine; the browser was what filled the field.

So this pass does what a tester does with a browser, and nothing a tester would have to judge:

- `autofill-trap`   Chrome's address autofill, driven through the DevTools protocol, fills
                    each form; a field it fills that nobody can see is a finding.
- `phone-width`     at 375 px the page can be scrolled sideways.
- `long-input`      after a long file name or entry, the page can be scrolled sideways.
- `ios-zoom`        a form field under 16 px, which makes iOS Safari zoom in on tap.
- `hidden-at-load`  much of the page is `visibility: hidden` until it is scrolled into view,
                    which keeps it from screen readers and the Tab key.
- `focus-visible`   a control the Tab key reaches looks the same focused and unfocused,
                    compared pixel for pixel.
- `keyboard`        a control that reacts to a click and not to Enter or Space.
- `get-form`        without JavaScript, a form sends personal fields in the address bar.
- `social-image`    the social preview image is missing or not the size the page declares.
- `links`           a link or a file the page loads answers 4xx; a live page answers 5xx.

Every finding is a measurement, filed `proven`, with the measured values as its evidence.

What it will not do, by construction: send a write. Every request the page makes with a method
other than GET, HEAD or OPTIONS is aborted in the browser, and so is every request to another
origin, so a form is never submitted, a payment never starts and no third party is called.
Links that look like they change state (log out, delete, unsubscribe) are never followed. The
site under test is the profile's `site:` block, or the URL given to `verdict-browse`: nothing
else is visited.

    verdict-browse https://example.com                     # a live site, look only
    verdict-browse http://127.0.0.1:{port}/ --start "npx next start -p {port}" --repo .
    verdict-local …                                         # with `site:` in profile.md

The browser is Playwright's (`pip install 'verdict-qa-mcp[browser]'`), driving the installed
Google Chrome when there is one: Chrome's autofill is not in the bundled Chromium. Without
either, the pass says so and measures nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
try:  # split out of this file by the structure pass; still importable here
    from .browser_js import (JS_AUTOFILL_PLAN, JS_FIELD_FACTS, JS_FILL_PLAN, JS_FOCUSED,
                             JS_KEY_CANDIDATES, JS_OVERFLOW, JS_PAGE, JS_REVEAL_DONE,
                             JS_REVEAL_INIT, JS_REVEAL_STEP, JS_VALUES, JS_WATCH_READ,
                             JS_WATCH_START, JS_ZOOM_DONE, JS_ZOOM_START, JS_ZOOM_STEP)
except ImportError:  # executed as a bare script
    from browser_js import (JS_AUTOFILL_PLAN, JS_FIELD_FACTS, JS_FILL_PLAN, JS_FOCUSED,
                            JS_KEY_CANDIDATES, JS_OVERFLOW, JS_PAGE, JS_REVEAL_DONE,
                            JS_REVEAL_INIT, JS_REVEAL_STEP, JS_VALUES, JS_WATCH_READ,
                            JS_WATCH_START, JS_ZOOM_DONE, JS_ZOOM_START, JS_ZOOM_STEP)
try:  # split out of this file by the structure pass; still importable here
    from .browser_source import source_of
except ImportError:  # executed as a bare script
    from browser_source import source_of
try:  # split out of this file by the structure pass; still importable here
    from .browser_forms import get_forms
except ImportError:  # executed as a bare script
    from browser_forms import get_forms
try:  # split out of this file by the structure pass; still importable here
    from .browser_config import (ADDRESS, ASSET_SUFFIX, BOT_WALL, BUDGET_S, CHECKS, DESKTOP,
                                 ENGINE, FOCUS_STOPS, FOCUS_STOPS_PER_PAGE, HIDDEN_MAJOR,
                                 HIDDEN_SHARE, KEY_CANDIDATES, KEY_CANDIDATES_PER_PAGE,
                                 LINK_CHECKS, LONG_NAME, MAX_PAGES, MIN_TEXT, NAV_TIMEOUT_MS,
                                 NOT_A_WRITE, NO_PLAYWRIGHT, PHONE, PLATFORM_PATHS, Pass,
                                 READY_S, REVEALED_SHARE, SETTLE_MS, STATEFUL_PATH, Site,
                                 SiteError, _list, make_site, origin_of,
                                 site_from as site_from)
except ImportError:  # executed as a bare script
    from browser_config import (ADDRESS, ASSET_SUFFIX, BOT_WALL, BUDGET_S, CHECKS, DESKTOP,
                                ENGINE, FOCUS_STOPS, FOCUS_STOPS_PER_PAGE, HIDDEN_MAJOR,
                                HIDDEN_SHARE, KEY_CANDIDATES, KEY_CANDIDATES_PER_PAGE,
                                LINK_CHECKS, LONG_NAME, MAX_PAGES, MIN_TEXT, NAV_TIMEOUT_MS,
                                NOT_A_WRITE, NO_PLAYWRIGHT, PHONE, PLATFORM_PATHS, Pass,
                                READY_S, REVEALED_SHARE, SETTLE_MS, STATEFUL_PATH, Site,
                                SiteError, _list, make_site, origin_of, site_from as site_from)
try:  # split out of this file by the structure pass; still importable here
    from .browser_findings import (configured, finding, marker as marker, marks_of as marks_of,
                                   resolved_by_measurement as resolved_by_measurement)
except ImportError:  # executed as a bare script
    from browser_findings import (configured, finding, marker as marker, marks_of as marks_of,
                                  resolved_by_measurement as resolved_by_measurement)
try:  # split out of this file by the structure pass; still importable here
    from .browser_images import image_size
except ImportError:  # executed as a bare script
    from browser_images import image_size
try:  # split out of this file by the structure pass; still importable here
    from .browser_server import start_server, stop_server, wait_ready
except ImportError:  # executed as a bare script
    from browser_server import start_server, stop_server, wait_ready

try:  # the optional extra: `pip install 'verdict-qa-mcp[browser]'`
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised where Playwright is absent
    sync_playwright = None

    class PlaywrightError(Exception):
        """Stands in for Playwright's error when Playwright is not installed."""


# ── the pass ──────────────────────────────────────────────────────────────────

class _Run:
    """One browser pass over one site. Holds the browser, the budget and what was measured."""

    def __init__(self, site: Site, repo: Path | None, log, browser, engine: str):
        self.site, self.repo, self.log = site, repo, log
        self.browser, self.engine = browser, engine
        self.deadline = time.monotonic() + site.budget_s
        self.result = Pass()
        self.third_party: dict = {}       # host → count
        self.writes: list = []            # "POST /api/x"
        self.pages: dict = {}             # path → {"status", "url", "links", "og", "fields"}
        self.order: list = []             # paths in the order they were visited
        self.link_from: dict = {}         # target path → [pages that link to it]
        self.missing_assets: dict = {}    # asset path → (status, [pages])
        self.server_errors: list = []
        self.wall: str | None = None
        self.robots = None
        self.focus_left = FOCUS_STOPS
        self.focus_seen: set = set()
        self.focus_cut: list = []         # pages whose Tab walk stopped at a cap
        self.moving: list = []            # controls whose surroundings never stopped moving
        self.keys_left = KEY_CANDIDATES
        self.key_seen: set = set()
        self.keys_cut: list = []          # pages with controls the caps left untried
        self.not_reached: list = []
        self.skipped_pages: list = []
        self.autofill_missing = False
        self.no_trigger: list = []
        self.hidden_pages: list = []
        self.unserved: list = []          # links a local server cannot answer for the deployment
        self._cdp = self._cdp_page = None

    # time and bookkeeping

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def out_of_time(self, what: str) -> bool:
        if self.left() > 0:
            return False
        note = f"the browser pass ran out of its {self.site.budget_s} s budget before {what}"
        if note not in self.result.not_tested:
            self.result.not_tested.append(note)
        return True

    def done(self, check: str, path: str) -> None:
        self.result.measured.add((check, path))

    def add(self, entry: dict) -> None:
        self.result.findings.append(entry)

    def on(self, check: str) -> bool:
        return check in self.site.checks

    # the network rule, the reason this pass is safe to point at a live site

    def guard(self, route, request) -> None:
        url = request.url
        if not url.startswith(("http://", "https://")):
            route.continue_()
            return
        if origin_of(url) != self.site.origin:
            host = urllib.parse.urlsplit(url).hostname or "?"
            self.third_party[host] = self.third_party.get(host, 0) + 1
            route.abort()
            return
        if request.method.upper() not in NOT_A_WRITE:
            self.writes.append(f"{request.method.upper()} {urllib.parse.urlsplit(url).path}")
            route.abort()
            return
        route.continue_()

    def context(self, **kwargs):
        ctx = self.browser.new_context(service_workers="block", accept_downloads=False,
                                       locale="en-US", **kwargs)
        ctx.route("**/*", self.guard)
        ctx.set_default_timeout(15_000)
        ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        return ctx

    @staticmethod
    def new_page(ctx):
        """A page that leaves when asked "leave this page?", and closes every other dialog."""
        page = ctx.new_page()

        def answer(dialog):
            try:
                if dialog.type == "beforeunload":
                    dialog.accept()
                else:
                    dialog.dismiss()
            except PlaywrightError:
                pass
        page.on("dialog", answer)
        return page

    def path_of(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        return parts.path or "/"

    def src(self, path: str) -> str | None:
        return source_of(self.repo, path)

    def goto(self, page, url: str):
        response = page.goto(url, wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=1_500)
        except PlaywrightError:
            pass
        page.wait_for_timeout(SETTLE_MS)
        return response

    def allowed(self, url: str) -> str | None:
        """Why a URL is not visited, or None when it may be."""
        path = self.path_of(url)
        if STATEFUL_PATH.search(path):
            return "its path reads like an action (log out, delete, unsubscribe)"
        if any(path.startswith(prefix) for prefix in self.site.skip):
            return "the profile's `skip`"
        if self.robots is not None and not self.robots.can_fetch(ENGINE, url):
            return "robots.txt"
        return None

    # 1. crawl, desktop: pages, links, and what only a desktop pass measures

    def crawl(self) -> None:
        if not self.site.loopback:
            robots = urllib.robotparser.RobotFileParser(self.site.origin + "/robots.txt")
            try:
                robots.read()
                self.robots = robots
            except (OSError, ValueError, UnicodeDecodeError):
                self.robots = None
        queue = [self.site.url] + list(self.site.pages)
        seen: set = set()
        ctx = self.context(viewport=DESKTOP)
        page = self.new_page(ctx)
        assets: dict = {}
        page.on("response", lambda r: self._asset(r, assets))
        try:
            while queue and len(self.order) < self.site.max_pages:
                url = queue.pop(0).split("#", 1)[0]
                path = self.path_of(url)
                if path in seen:
                    continue
                seen.add(path)
                why = self.allowed(url)
                if why:
                    self.skipped_pages.append(f"{path} ({why})")
                    continue
                if self.out_of_time(f"visiting {path}"):
                    break
                assets.clear()
                assets["__page__"] = path
                try:
                    response = self.goto(page, url)
                except PlaywrightError as exc:
                    self.not_reached.append(f"{path} ({str(exc).splitlines()[0][:80]})")
                    continue
                status = response.status if response is not None else None
                final = page.url.split("#", 1)[0]
                if origin_of(final) != self.site.origin:
                    self.not_reached.append(f"{path} (redirected off the site)")
                    continue
                if status in (403, 429, 503) and BOT_WALL.search(page.content()[:20000]):
                    self.wall = f"{path} answered {status} with a bot challenge"
                    break
                info = page.evaluate(JS_PAGE)
                self.pages[path] = {"status": status, "url": url, "og": info["og"],
                                    "fields": info["fields"], "forms": info["forms"],
                                    "get_forms": info["getForms"]}
                self.order.append(path)
                self.log(f"{path} {status} · {info['forms']} form(s)")
                links = []
                for link in info["links"]:
                    href = link["href"].split("#", 1)[0]
                    if not href.startswith(("http://", "https://")) or origin_of(href) != self.site.origin:
                        continue
                    target = self.path_of(href)
                    links.append(target)
                    self.link_from.setdefault(target, [])
                    if path not in self.link_from[target]:
                        self.link_from[target].append(path)
                    if not ASSET_SUFFIX.search(target) and target not in seen:
                        queue.append(href)
                self.pages[path]["links"] = sorted(set(links))
                if status is not None and status >= 400:
                    continue
                if self.on("hidden-at-load"):
                    self.hidden_at_load(page, path)
                if self.on("autofill-trap") and info["fields"]:
                    self.autofill(ctx, page, url, path)
                # Called on every page even once a run-wide cap is spent, so a page the cap
                # kept from being checked is named in `not_tested` rather than passed over.
                if self.on("focus-visible"):
                    self.focus_visible(page, url, path)
                if self.on("keyboard"):
                    self.keyboard(page, url, path)
            if queue and len(self.order) >= self.site.max_pages:
                rest = sorted({self.path_of(u) for u in queue} - set(self.order))
                if rest:
                    self.result.not_tested.append(
                        f"{len(rest)} page(s) beyond the cap of {self.site.max_pages} were not "
                        f"visited: {', '.join(rest[:8])}{' …' if len(rest) > 8 else ''}")
        finally:
            ctx.close()

    def _asset(self, response, assets: dict) -> None:
        try:
            request = response.request
            if request.resource_type not in ("image", "stylesheet", "script", "font", "media"):
                return
            if origin_of(response.url) != self.site.origin or response.status < 400:
                return
            if "_rsc=" in response.url:
                return
            path = self.path_of(response.url)
            status, pages = self.missing_assets.setdefault(path, (response.status, []))
            page = assets.get("__page__")
            if page and page not in pages:
                pages.append(page)
        except PlaywrightError:
            return

    # 2. autofill: Chrome fills each form from a synthetic address; who got filled?

    def autofill(self, ctx, page, url: str, path: str) -> None:
        if self.autofill_missing:
            return
        cdp = self._cdp
        if cdp is None or self._cdp_page is not page:
            try:
                cdp = ctx.new_cdp_session(page)
                cdp.send("Autofill.enable")
            except PlaywrightError:
                self.autofill_missing = True
                return
            self._cdp, self._cdp_page = cdp, page
        plan = page.evaluate(JS_AUTOFILL_PLAN)
        with_trigger = [g for g in plan if g["trigger"] is not None]
        if not with_trigger:
            if plan:
                self.no_trigger.append(path)
            self.done("autofill-trap", path)
            return
        found = []
        complete = True
        for n, group in enumerate(with_trigger):
            if n:
                self.goto(page, url)
                page.evaluate(JS_AUTOFILL_PLAN)
            before = page.evaluate(JS_VALUES)
            try:
                root = cdp.send("DOM.getDocument", {"depth": 0})["root"]
                node_id = cdp.send("DOM.querySelector", {
                    "nodeId": root["nodeId"],
                    "selector": f'[data-verdict-field="{group["trigger"]}"]'})["nodeId"]
                backend = cdp.send("DOM.describeNode", {"nodeId": node_id})["node"]["backendNodeId"]
                frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
            except PlaywrightError:
                complete = False
                continue
            filled = None
            for _attempt in range(2):
                try:
                    cdp.send("Autofill.trigger", {"fieldId": backend, "frameId": frame,
                                                  "address": ADDRESS})
                    filled = True
                    break
                except PlaywrightError:
                    page.wait_for_timeout(800)
            if not filled:
                complete = False
                continue
            after = before
            for _ in range(10):
                page.wait_for_timeout(200)
                after = page.evaluate(JS_VALUES)
                if after != before:
                    break
            changed = [int(i) for i, v in after.items() if v and v != before.get(i)]
            if not changed:
                continue
            for fact in page.evaluate(JS_FIELD_FACTS, changed):
                if fact and fact["hidden"]:
                    found.append((group, fact))
        if complete:
            self.done("autofill-trap", path)
        for group, fact in found:
            trap = bool(fact["signs"]) or re.search(
                r"company|website|url|fax|honey|hp|trap|bot", fact["name"] or "", re.I)
            lines = [f"on {path}, Chrome's address autofill, started from {group['triggerDesc']}, "
                     f"wrote {fact['value']!r} into {fact['desc']}, which nobody can see: "
                     f"{fact['hidden']}"]
            if trap:
                lines.append(f"{fact['desc']} is marked like a bot trap"
                             + (f" ({', '.join(fact['signs'])})" if fact["signs"] else "")
                             + ": a form that treats a filled trap as a bot turns away every "
                               "visitor who lets autofill fill the form")
            self.add(finding(
                "autofill-trap", path, self.src(path),
                f"Autofill fills a field nobody can see: `{fact['name'] or fact['desc']}` on {path}",
                "Major", "P1", lines,
                "Browser autofill fills every field it recognises that is rendered, including "
                "fields moved off-screen, shrunk to nothing or made transparent. Only "
                "display:none, visibility:hidden, disabled and type=hidden keep a field out of "
                "it; autocomplete=\"off\" and tabindex=\"-1\" do not.",
                "A hidden field autofill writes into receives the visitor's data without them "
                "seeing it. When it is a bot trap, a real person who uses autofill is treated as "
                "a bot. Hide a trap with display:none or type=hidden, or give it a name autofill "
                "does not recognise; then check the form end to end with autofill on.",
                self.engine))

    # 3. hidden at load: text and controls `visibility: hidden` until scrolled to

    def hidden_at_load(self, page, path: str) -> None:
        try:
            start = page.evaluate(JS_REVEAL_INIT)
            total = start["shown"] + start["hidden"]
            if total < MIN_TEXT or start["hidden"] < HIDDEN_SHARE * total:
                self.done("hidden-at-load", path)
                return
            height = start["height"]
            step = DESKTOP["height"]
            y = 0
            for _ in range(60):
                y += step
                page.evaluate("(y) => window.scrollTo(0, y)", y)
                page.wait_for_timeout(80)
                height = page.evaluate(JS_REVEAL_STEP) or height
                if y >= height:
                    break
            page.wait_for_timeout(300)
            page.evaluate(JS_REVEAL_STEP)
            done = page.evaluate(JS_REVEAL_DONE)
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(150)
        except PlaywrightError:
            return
        self.done("hidden-at-load", path)
        if not done or done["revealed"] < REVEALED_SHARE * start["hidden"]:
            return
        self.hidden_pages.append({"path": path, "share": start["hidden"] / total,
                                  "hidden": start["hidden"], "total": total,
                                  "revealed": done["revealed"] / start["hidden"],
                                  "controls": start["fHidden"],
                                  "of": start["fHidden"] + start["fShown"],
                                  "example": done.get("example") or ""})

    def report_hidden(self) -> None:
        """One finding for the whole site: a reveal effect is one cause, however many pages
        carry it (a Next.js site, 2026-11-14: one effect, 29 pages)."""
        if not self.hidden_pages:
            return
        pages = self.hidden_pages
        first = pages[0]
        worst = max(p["share"] for p in pages)
        lines = [f"on {first['path']} at {DESKTOP['width']}×{DESKTOP['height']}, "
                 f"{round(100 * first['share'])}% of the page's text ({first['hidden']} of "
                 f"{first['total']} characters) is `visibility: hidden` when it loads; "
                 f"scrolling through the page shows {round(100 * first['revealed'])}% of it"]
        if first["controls"]:
            lines.append(f"{first['controls']} of {first['of']} links, buttons and fields there "
                         "are hidden the same way, so Tab skips them until they are scrolled "
                         "into view")
        if first["example"]:
            lines.append(f"for example {first['example']}")
        if len(pages) > 1:
            listed = ", ".join(f"{p['path']} {round(100 * p['share'])}%" for p in pages[1:13])
            lines.append(f"the same on {len(pages) - 1} more page(s): {listed}"
                         + (" …" if len(pages) > 13 else ""))
        self.add(finding(
            "hidden-at-load", first["path"], self.src(first["path"]),
            "Content is hidden from screen readers and the keyboard until it is scrolled into view",
            "Major" if worst >= HIDDEN_MAJOR else "Minor", "P2", lines,
            "A reveal-on-scroll effect sets `visibility: hidden` (for example GSAP's autoAlpha) "
            "until the element enters the viewport. Hidden that way, the element is out of the "
            "accessibility tree and out of the Tab order, and a screen reader cannot scroll to "
            "what it cannot see.",
            "Animate opacity and transform only, leave visibility alone, and skip the effect "
            "under prefers-reduced-motion; then the content is there for assistive technology "
            "from the first paint.", self.engine, also=[p["path"] for p in pages[1:]]))

    # 4. focus: Tab through the page; is there any visible difference focused vs not?

    @staticmethod
    def settle_scroll(page, tries: int = 12) -> None:
        """Wait for a smooth scroll to finish: the position read twice, 100 ms apart, agrees."""
        last = None
        for _ in range(tries):
            here = page.evaluate("() => [scrollX, scrollY]")
            if here == last:
                return
            last = here
            page.wait_for_timeout(100)

    def focused(self, page, before=None):
        """The focused element, read after the page has finished scrolling to it. A smooth
        scroll moves it into view over several hundred milliseconds (a Next.js site, 2026-11-14:
        read at once, 13 of 25 links looked off-screen); only an element still off-screen
        when the scrolling stops is one focus really went to out of sight. `before` is the
        scroll position before the Tab: a page that did not move needs no waiting."""
        info = page.evaluate(JS_FOCUSED)
        for _ in range(8):
            if info is None or not info["offscreen"]:
                break
            page.wait_for_timeout(150)
            info = page.evaluate(JS_FOCUSED)
        if info is None:
            return None
        if before is None or page.evaluate("() => [scrollX, scrollY]") != before:
            self.settle_scroll(page)
            info = page.evaluate(JS_FOCUSED)
        return info

    @staticmethod
    def still(page, clip, tries: int = 10):
        """A screenshot of `clip` once two in a row agree, or None if it never stops moving.
        `animations="disabled"` settles CSS animations only; a script-driven fade (a reveal on
        scroll) keeps going, and one screenshot taken mid-fade against one taken after it
        compares a fade, not a focus ring (a Next.js site, 2026-11-14)."""
        last = page.screenshot(clip=clip, animations="disabled", caret="hide")
        for _ in range(tries):
            page.wait_for_timeout(120)
            shot = page.screenshot(clip=clip, animations="disabled", caret="hide")
            if shot == last:
                return shot
            last = shot
        return None

    @staticmethod
    def scroll_through(page, step: int, each: str | None = None) -> None:
        """Scroll to the bottom and back, so what a page reveals on scroll has been revealed;
        `each` runs at every step."""
        try:
            y = 0
            if each:
                page.evaluate(each)
            for _ in range(60):
                y += step
                page.evaluate("(y) => window.scrollTo(0, y)", y)
                page.wait_for_timeout(80)
                if each:
                    page.evaluate(each)
                if y >= page.evaluate("() => document.documentElement.scrollHeight"):
                    break
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
        except PlaywrightError:
            pass

    def focus_visible(self, page, url: str, path: str) -> None:
        try:
            page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); }")
            seen: set = set()
            invisible = []
            stops = 0
            ended = False          # Tab came back round, or left the page: every stop was seen
            while stops < min(FOCUS_STOPS_PER_PAGE, self.focus_left):
                before = page.evaluate("() => [scrollX, scrollY]")
                page.keyboard.press("Tab")
                info = self.focused(page, before)
                if info is None or info["sig"] in seen:
                    ended = True
                    break
                seen.add(info["sig"])
                stops += 1
                # A control the header or footer repeats is judged once, on the first page.
                if info["textEntry"] or info["frame"] or info["sig"] in self.focus_seen:
                    continue
                self.focus_seen.add(info["sig"])
                if info["offscreen"]:
                    invisible.append((info["desc"], "focus moved to it while it is off-screen"))
                    continue
                clip = info["clip"]
                if clip["width"] < 1 or clip["height"] < 1:
                    continue
                focused = self.still(page, clip)
                page.evaluate("() => document.activeElement && document.activeElement.blur()")
                plain = self.still(page, clip)
                if focused is None or plain is None:
                    self.moving.append(f"{path} {info['desc'][:60]}")
                elif focused == plain:
                    invisible.append((info["desc"], "pixel for pixel the same focused and "
                                                    "unfocused"))
            self.focus_left -= stops
        except PlaywrightError:
            return
        if ended:
            self.done("focus-visible", path)
        else:
            self.focus_cut.append(path)
        if not invisible:
            return
        lines = [f"on {path}, Tab reached {stops} control(s); {len(invisible)} show no change "
                 f"when focused: " + "; ".join(f"{d} ({why})" for d, why in invisible[:8])
                 + (" …" if len(invisible) > 8 else "")]
        self.add(finding(
            "focus-visible", path, self.src(path),
            f"Keyboard focus is invisible on controls on {path}",
            "Minor", "P2", lines,
            "The control's focus style is removed (outline: none, or a hidden input whose visible "
            "wrapper shows nothing on :focus-within) and nothing replaces it.",
            "A keyboard user cannot tell where they are. Give each control a :focus-visible "
            "style; for a visually hidden input, style its visible wrapper with :focus-within "
            "(WCAG 2.4.7).", self.engine))

    # 5. keyboard: a control that reacts to a click must react to Enter (and Space)

    def _reacts(self, page, url: str, index: int, action: str) -> bool | None:
        events = {"n": 0}

        def bump(*_args):
            events["n"] += 1

        def chooser(fc):
            events["n"] += 1

        def dialog(d):
            events["n"] += 1
            try:
                d.dismiss()
            except PlaywrightError:
                pass

        def popup(p):
            events["n"] += 1
            try:
                p.close()
            except PlaywrightError:
                pass

        self.goto(page, url)
        page.evaluate(JS_KEY_CANDIDATES)
        target = page.locator(f'[data-verdict-key="{index}"]')
        if target.count() != 1:
            return None
        handlers = [("request", bump), ("filechooser", chooser), ("dialog", dialog),
                    ("popup", popup), ("framenavigated", bump)]
        try:
            target.evaluate("(el) => el.focus()")
            page.wait_for_timeout(150)
            self.settle_scroll(page)
            before = page.evaluate("() => [scrollX, scrollY]")
            page.evaluate(JS_WATCH_START)
            for name, handler in handlers:
                page.on(name, handler)
            if action == "click":
                target.click(timeout=3_000, no_wait_after=True)
            else:
                page.keyboard.press(action)
            page.wait_for_timeout(500)
            try:
                mutations = page.evaluate(JS_WATCH_READ)
                after = page.evaluate("() => [scrollX, scrollY]")
            except PlaywrightError:
                return True            # the page went away: that is a reaction
            if action == "Space" and after != before and not events["n"]:
                # Space on something that is not a button scrolls the page, and a scroll sets
                # off whatever the page animates on scroll. That is the browser's default, not
                # the control: a control that handles Space stops the scroll.
                return False
            return bool(mutations or events["n"] or page.url.split("#")[0] != url.split("#")[0])
        except PlaywrightError:
            return None
        finally:
            for name, handler in handlers:
                try:
                    page.remove_listener(name, handler)
                except (PlaywrightError, KeyError, ValueError):
                    pass

    def keyboard(self, page, url: str, path: str) -> None:
        try:
            candidates = page.evaluate(JS_KEY_CANDIDATES)
        except PlaywrightError:
            return
        # A control the header or footer repeats on every page is tried once, on the first page.
        todo = [c for c in candidates if c["desc"] not in self.key_seen]
        batch = todo[:min(KEY_CANDIDATES_PER_PAGE, self.keys_left)]
        complete = len(batch) == len(todo)
        if not complete:
            self.keys_cut.append(path)
        dead = []
        for cand in batch:
            self.key_seen.add(cand["desc"])
            self.keys_left -= 1
            keys = ("Enter",) if cand["role"] == "link" else ("Enter", "Space")
            clicked = self._reacts(page, url, cand["i"], "click")
            if clicked is None:
                complete = False
                continue
            if not clicked:
                continue
            silent = []
            for key in keys:
                reacted = self._reacts(page, url, cand["i"], key)
                if reacted is None:
                    complete = False
                elif not reacted:
                    silent.append(key)
            if silent:
                dead.append((cand["desc"], silent))
        if batch:
            try:
                self.goto(page, url)
            except PlaywrightError:
                pass
        if complete:
            self.done("keyboard", path)
        if not dead:
            return
        self.add(finding(
            "keyboard", path, self.src(path),
            f"Controls on {path} work with a click and not from the keyboard",
            "Major", "P2",
            [f"on {path}: " + "; ".join(
                f"{desc} reacts to a click (the page changed, a request went out or a file "
                f"chooser opened) and does nothing on {' or '.join(silent)} while it has "
                "keyboard focus" for desc, silent in dead[:6])],
            "An element given role=\"button\" (or role=\"link\") and a click handler does not "
            "get the keyboard behaviour of the element it imitates: Enter and Space do "
            "nothing unless a keydown handler is added.",
            "Use a real <button> (or <label> for a file input, <a href> for a link), or "
            "handle Enter and Space on keydown (WCAG 2.1.1).", self.engine))

    # 6. phone: sideways scroll at load, iOS zoom, and after long values

    def phone(self) -> None:
        if not any(self.on(c) for c in ("phone-width", "long-input", "ios-zoom")):
            return
        ctx = self.context(viewport=PHONE, is_mobile=True, has_touch=True,
                           device_scale_factor=2)
        page = self.new_page(ctx)
        wide: dict = {}             # widest elements → [(page, measurement)]
        zooms: list = []            # [(page, fields under 16 px)]
        try:
            for path in self.order:
                info = self.pages[path]
                if info["status"] is not None and info["status"] >= 400:
                    continue
                if self.out_of_time(f"the phone checks on {path}"):
                    break
                zooming = self.on("ios-zoom") and info.get("fields")
                try:
                    self.goto(page, info["url"])
                    over = page.evaluate(JS_OVERFLOW)
                    if zooming or over:
                        # A page is scrolled through only when it needs it: to measure fields
                        # a reveal effect hides at load, or to see whether a sideways scroll
                        # outlasts the effects (an element sliding in from the side widens the
                        # page only until it arrives).
                        if zooming:
                            page.evaluate(JS_ZOOM_START)
                        self.scroll_through(page, PHONE["height"],
                                            each=JS_ZOOM_STEP if zooming else None)
                        over = page.evaluate(JS_OVERFLOW)
                except PlaywrightError:
                    continue
                if self.on("phone-width"):
                    self.done("phone-width", path)
                    if over:
                        # One element (a header, a footer) can widen every page: one finding
                        # per element, with every page it widens.
                        sig = tuple(c.split(" (right edge")[0] for c in over["culprits"]) or ("",)
                        wide.setdefault(sig, []).append((path, over))
                if zooming:
                    try:
                        zoom = page.evaluate(JS_ZOOM_DONE)
                    except PlaywrightError:
                        zoom = None
                    if zoom is not None:
                        self.done("ios-zoom", path)
                        if zoom["fields"] and not zoom["locked"]:
                            zooms.append((path, zoom["fields"]))
                if self.on("long-input") and info.get("fields") and not over:
                    self.long_input(page, path)
        finally:
            ctx.close()
        for hits in wide.values():
            path, over = hits[0]
            self.add(finding(
                "phone-width", path, self.src(path),
                f"The page scrolls sideways on a phone: {path}",
                "Major", "P1",
                [f"on {path} at {PHONE['width']}×{PHONE['height']} the page can be scrolled "
                 f"{over['moved']} px sideways; widest: "
                 + "; ".join(over["culprits"] or ["(no single element)"])]
                + ([f"the same element widens {len(hits) - 1} more page(s): "
                    + ", ".join(p for p, _ in hits[1:9]) + (" …" if len(hits) > 9 else "")]
                   if len(hits) > 1 else []),
                "An element is wider than the phone's screen and nothing contains it (a fixed "
                "width, a long unbroken word, a wide table or image).",
                "Contain the element (max-width: 100%, overflow-wrap: anywhere, or a scroll box "
                "of its own) so the page itself never scrolls sideways.", self.engine,
                also=[p for p, _ in hits[1:]]))
        if zooms:
            # One stylesheet sets the size of every field, so one finding for the site.
            path, fields = zooms[0]
            self.add(finding(
                "ios-zoom", path, self.src(path),
                "Form fields under 16 px make iOS Safari zoom in when tapped",
                "Minor", "P3",
                [f"on {path} at {PHONE['width']} px: "
                 + "; ".join(f"{f['desc']} at {f['size']} px" for f in fields[:6])
                 + (" …" if len(fields) > 6 else "")]
                + [f"on {p}: " + "; ".join(f"{f['desc']} at {f['size']} px" for f in fs[:3])
                   + (" …" if len(fs) > 3 else "") for p, fs in zooms[1:6]]
                + ([f"and {len(zooms) - 6} more page(s)"] if len(zooms) > 6 else []),
                "iOS Safari zooms the page in when a field whose font size is under 16 px gets "
                "focus, and does not zoom back out.",
                "Give text fields a font size of at least 16 px on small screens (1rem); do "
                "not disable zoom in the viewport tag instead.", self.engine,
                also=[p for p, _ in zooms[1:]]))

    def long_input(self, page, path: str) -> None:
        try:
            plan = page.evaluate(JS_FILL_PLAN)
        except PlaywrightError:
            return
        if not plan["texts"] and not plan["files"]:
            self.done("long-input", path)
            return
        filled = []
        for f in plan["files"]:
            accept = [a.strip() for a in f["accept"].split(",") if a.strip().startswith(".")]
            ext = accept[0] if accept else ".pdf"
            stem = ("Quarterly-fuel-and-mileage-records-for-every-truck-in-the-fleet-"
                    "January-through-March-final-version-signed")
            name = (stem * 2)[:LONG_NAME - len(ext)] + ext
            try:
                page.locator(f'[data-verdict-fill="{f["i"]}"]').set_input_files(
                    files=[{"name": name, "mimeType": "application/octet-stream",
                            "buffer": b"verdict-browse test file\n"}])
                filled.append(f"{f['desc']} ← a {len(name)}-character file name")
            except PlaywrightError:
                continue
        for f in plan["texts"]:
            value = ("Supercalifragilisticexpialidocious-" * 5)[:min(LONG_NAME, f["max"] or LONG_NAME)]
            try:
                page.locator(f'[data-verdict-fill="{f["i"]}"]').fill(value, timeout=3_000)
                filled.append(f"{f['desc']} ← {len(value)} characters with no space")
            except PlaywrightError:
                continue
        try:
            page.wait_for_timeout(SETTLE_MS)
            over = page.evaluate(JS_OVERFLOW)
        except PlaywrightError:
            return
        self.done("long-input", path)
        if not over:
            return
        kind = "file name" if plan["files"] else "entry"
        self.add(finding(
            "long-input", path, self.src(path),
            f"A long {kind} pushes {path} wider than a phone screen",
            "Major", "P2",
            [f"on {path} at {PHONE['width']}×{PHONE['height']}, after "
             + "; ".join(filled[:6]) + f", the page can be scrolled {over['moved']} px "
             "sideways; widest: " + "; ".join(over["culprits"] or ["(no single element)"])],
            "The page shows what was entered (a chosen file's name, a preview) in an element "
            "that does not wrap a long unbroken string.",
            "Let the element wrap (overflow-wrap: anywhere; min-width: 0 on flex and grid "
            "children) or truncate it with an ellipsis and the full value in a title.",
            self.engine))

    # 7. without JavaScript: a GET form with personal fields

    def no_js(self) -> None:
        if not self.on("get-form"):
            return
        loaded = [p for p in self.order if (self.pages[p]["status"] or 0) < 400]
        pages = [p for p in loaded if self.pages[p].get("get_forms")]
        for path in loaded:
            if path not in pages:
                self.done("get-form", path)      # no form there could go out as a GET
        if not pages:
            return
        ctx = self.context(viewport=DESKTOP, java_script_enabled=False)
        page = self.new_page(ctx)
        try:
            for path in pages:
                if self.out_of_time(f"the no-JavaScript check on {path}"):
                    break
                try:
                    self.goto(page, self.pages[path]["url"])
                    html = page.content()
                except PlaywrightError:
                    continue
                self.done("get-form", path)
                for form in get_forms(html):
                    secret = form["secret"]
                    self.add(finding(
                        "get-form", path, self.src(path),
                        f"Without JavaScript, the form on {path} sends "
                        f"{', '.join(form['fields'][:4])} in the address bar",
                        "Major" if secret else "Minor", "P1" if secret else "P2",
                        [f"on {path} with JavaScript off, the form has method "
                         f"{form['method'].upper()} (action {form['action'] or 'this page'!r}) "
                         f"and the fields {', '.join(form['fields'])}: submitting it puts each "
                         "value in the URL"],
                        "The form relies on a JavaScript submit handler and has no method=\"post\"; "
                        "before the script loads, or when it fails, the browser submits it the "
                        "default way, as a GET.",
                        "Set method=\"post\" (and an action that handles it) so a submission "
                        "without JavaScript never writes personal data into browser history, "
                        "server logs and the Referer header.", self.engine))
        finally:
            ctx.close()

    # 8. links, files the pages load, social images

    def links(self) -> None:
        if not self.on("links"):
            return
        # A link counts only from a page that loaded, and never to itself: an error page's own
        # skip link resolves to the error page (a Next.js site, 2026-11-14, a 404 "linking" to itself).
        loaded = {p for p in self.order if (self.pages[p]["status"] or 0) < 400}
        sources_of = {t: [s for s in sources if s in loaded and s != t]
                      for t, sources in self.link_from.items()}
        ctx = self.browser.new_context()
        request = ctx.request
        checked: dict = {p: self.pages[p]["status"] for p in self.order}
        try:
            unvisited = [t for t in self.link_from if t not in checked and sources_of.get(t)
                         and self.allowed(self.site.origin + t) is None]
            for target in unvisited[:LINK_CHECKS]:
                if self.out_of_time("checking links"):
                    break
                try:
                    response = request.get(self.site.origin + target, max_redirects=5,
                                           timeout=15_000)
                    checked[target] = response.status
                except PlaywrightError:
                    continue
            if len(unvisited) > LINK_CHECKS:
                self.result.not_tested.append(
                    f"{len(unvisited) - LINK_CHECKS} linked address(es) beyond {LINK_CHECKS} "
                    "were not checked")
        finally:
            ctx.close()
        for path in self.order:
            targets = self.pages[path].get("links") or []
            if all(t in checked for t in targets):
                self.done("links", path)
        seeds = {self.path_of(u) for u in self.site.pages}
        for target, status in checked.items():
            if status is None or status < 400:
                continue
            sources = sources_of.get(target) or []
            if self.site.loopback and target.startswith(PLATFORM_PATHS):
                self.unserved.append(f"{target} ({status}; served by the hosting platform)")
                continue
            routed = configured(self.repo, target) if self.site.loopback else None
            if routed:
                self.unserved.append(f"{target} ({status}; {routed} routes it, with settings a "
                                     "local server may not have)")
                continue
            if not sources and target in seeds:
                self.not_reached.append(f"{target} (a page given to visit answered {status})")
                continue
            if status >= 500:
                if self.site.loopback:
                    self.server_errors.append(f"{target} ({status})")
                    continue
                first = sources[0] if sources else target
                self.add(finding(
                    "links", first, self.src(target),
                    f"A page answers {status}: {target}",
                    "Major", "P1",
                    [f"GET {target} answered {status}"
                     + (f"; linked from {', '.join(sources[:5])}" if sources else "")],
                    "The server failed on a plain GET of a page the site links to.",
                    "Find the failing request in the server log; a page a visitor can reach "
                    "must not fail.", self.engine))
                continue
            if not sources:
                continue
            first = sources[0]
            self.add(finding(
                "links", first, self.src(first),
                f"Broken link: {target} answers {status}",
                "Minor", "P2",
                [f"on {first}, a link to {target} answers {status}"
                 + (f"; also linked from {', '.join(sources[1:5])}" if len(sources) > 1 else "")],
                "A link points at an address the site does not serve.",
                "Fix or remove the link (and redirect the old address if it ever existed).",
                self.engine))
        for asset, (status, pages) in sorted(self.missing_assets.items()):
            if not pages:
                continue
            if self.site.loopback and asset.startswith(PLATFORM_PATHS):
                self.unserved.append(f"{asset} ({status}; served by the hosting platform)")
                continue
            self.add(finding(
                "links", pages[0], self.src(pages[0]),
                f"A file the page loads is missing: {asset} answers {status}",
                "Minor", "P3",
                [f"on {pages[0]}, the page requests {asset} and gets {status}"
                 + (f"; the same on {', '.join(pages[1:5])}" if len(pages) > 1 else "")],
                "An image, stylesheet, script or font the page references is not served.",
                "Serve the file or drop the reference.", self.engine))

    def social(self) -> None:
        if not self.on("social-image"):
            return
        by_image: dict = {}
        for path in self.order:
            og = self.pages[path].get("og") or {}
            if og.get("image"):
                by_image.setdefault(og["image"], []).append((path, og))
        if not by_image:
            for path in self.order:
                self.done("social-image", path)
            return
        ctx = self.browser.new_context()
        try:
            for image, uses in by_image.items():
                absolute = urllib.parse.urljoin(self.pages[uses[0][0]]["url"], image)
                if origin_of(absolute) != self.site.origin:
                    if not self.site.loopback:
                        continue
                    # A local build still names its production host (Next's metadataBase, for
                    # one): the image is the same file at the same path on the local server.
                    parts = urllib.parse.urlsplit(absolute)
                    absolute = self.site.origin + parts.path + (f"?{parts.query}" if parts.query else "")
                if self.out_of_time("checking social images"):
                    break
                try:
                    response = ctx.request.get(absolute, timeout=15_000)
                    body = response.body() if response.status < 400 else b""
                except PlaywrightError:
                    continue
                for path, _og in uses:
                    self.done("social-image", path)
                path, og = uses[0]
                pages = [p for p, _ in uses]
                where = self.path_of(absolute)
                also = [f"the same image is set on {', '.join(pages[1:6])}"] if len(pages) > 1 else []
                if response.status >= 400:
                    self.add(finding(
                        "social-image", path, self.src(path),
                        f"The social preview image is missing: {where} answers {response.status}",
                        "Minor", "P3", [f"on {path}, og:image is {where}, which answers "
                                        f"{response.status}"] + also,
                        "The page names a preview image the site does not serve.",
                        "Serve the image or point og:image at one that exists.", self.engine))
                    continue
                size = image_size(body)
                try:
                    declared = (int(og["width"]), int(og["height"])) if og.get("width") and og.get("height") else None
                except ValueError:
                    declared = None
                if size and declared and tuple(size) != declared:
                    self.add(finding(
                        "social-image", path, self.src(path),
                        f"The social preview image {where} is {size[0]}×{size[1]}, not the "
                        f"{declared[0]}×{declared[1]} the page declares",
                        "Minor", "P3",
                        [f"on {path}, og:image:width and og:image:height say "
                         f"{declared[0]}×{declared[1]}; the image served at {where} is "
                         f"{size[0]}×{size[1]}"] + also,
                        "The declared size and the real image disagree.",
                        "Declare the image's real size, or serve one that is that size "
                        "(1200×630 is the usual preview).", self.engine))
        finally:
            ctx.close()

    # the record

    def summarise(self) -> None:
        r = self.result
        if self.wall:
            r.not_tested.insert(0, f"stopped at a bot wall: {self.wall}; pages after it were not "
                                   "visited and nothing was filed from it")
        if self.autofill_missing and self.on("autofill-trap"):
            r.not_tested.append("the autofill check did not run: this browser has no autofill in "
                                "its DevTools protocol (Chrome's is needed; the bundled Chromium "
                                "has none). Install Google Chrome")
        if self.no_trigger:
            r.not_tested.append("autofill was not tried on form(s) with no field it recognises: "
                                + ", ".join(sorted(set(self.no_trigger))[:8]))
        if self.focus_cut:
            r.not_tested.append(f"the Tab walk stopped at its cap of {FOCUS_STOPS_PER_PAGE} stops a "
                                f"page ({FOCUS_STOPS} a run) before the end of "
                                f"{len(self.focus_cut)} page(s): " + ", ".join(self.focus_cut[:8])
                                + (" …" if len(self.focus_cut) > 8 else ""))
        if self.moving:
            r.not_tested.append(f"{len(self.moving)} control(s) whose surroundings never stopped "
                                "moving, so focused and unfocused could not be compared: "
                                + ", ".join(self.moving[:6]) + (" …" if len(self.moving) > 6 else ""))
        if self.keys_cut:
            r.not_tested.append(f"controls left untried by the keyboard check's cap of "
                                f"{KEY_CANDIDATES_PER_PAGE} a page ({KEY_CANDIDATES} a run), on "
                                + ", ".join(self.keys_cut[:8])
                                + (" …" if len(self.keys_cut) > 8 else ""))
        r.not_tested.append("forms were not submitted: this pass sends GET requests only and "
                            "aborts every write, so what the server does with a submission (a "
                            "dropped message, a crash on odd input, an error the page never "
                            "shows) was not exercised")
        if self.third_party:
            hosts = sorted(self.third_party, key=lambda h: -self.third_party[h])
            r.not_tested.append(f"requests to {len(hosts)} other host(s) were blocked, so what "
                                f"they load was not seen: {', '.join(hosts[:8])}"
                                + (" …" if len(hosts) > 8 else ""))
        if self.writes:
            uniq = list(dict.fromkeys(self.writes))
            r.not_tested.append(f"{len(self.writes)} write request(s) the pages made were "
                                f"aborted: {', '.join(uniq[:6])}" + (" …" if len(uniq) > 6 else ""))
        if self.server_errors:
            r.not_tested.append("page(s) that answered 5xx under the local server were not filed — "
                                "with no secrets configured that may be the environment: "
                                + ", ".join(self.server_errors[:8]))
        if self.unserved:
            r.not_tested.append("address(es) a local server cannot answer the way the deployment "
                                "does were not filed: " + ", ".join(self.unserved[:8]))
        if self.not_reached:
            r.not_tested.append("page(s) not reached: " + ", ".join(self.not_reached[:8]))
        if self.skipped_pages:
            r.not_tested.append("page(s) never requested: " + ", ".join(self.skipped_pages[:8]))
        r.not_tested.append("one engine, Chrome: Safari and Firefox were not run, so the iOS zoom "
                            "check reads font sizes rather than driving iOS; frames were not "
                            "checked")
        r.facts.update({
            "url": self.site.url if not self.site.loopback else self.path_of(self.site.url),
            "browser": self.engine,
            "pages": [{"path": p, "status": self.pages[p]["status"]} for p in self.order],
            "checks": list(self.site.checks),
            "third_party_blocked": dict(sorted(self.third_party.items())),
            "writes_blocked": list(dict.fromkeys(self.writes)),
            "findings": len(r.findings),
        })


def _launch(pw):
    """The installed Google Chrome first (it has the autofill the autofill check drives), then
    Playwright's own Chromium. → (browser, "Chrome 157.0…") or (None, why)."""
    errors = []
    for kwargs in ({"channel": "chrome"}, {}):
        try:
            browser = pw.chromium.launch(headless=True, **kwargs)
            name = "Chrome" if kwargs else "Chromium"
            return browser, f"{name} {browser.version} (headless)"
        except PlaywrightError as exc:
            errors.append(str(exc).splitlines()[0][:120])
    return None, "; ".join(errors)


def browse(site: Site, repo: Path | None = None, log=None, server_log: Path | None = None) -> Pass:
    """One pass over one site. Never raises for the site's sake: what could not be done is a
    `not_tested` line, and the facts say what was."""
    log = log or (lambda message: print(f"{ENGINE}: {message}", file=sys.stderr))
    started = time.monotonic()
    if sync_playwright is None:
        return Pass(not_tested=[NO_PLAYWRIGHT], facts={"skipped": "playwright not installed"})
    server = None
    try:
        if site.start:
            log(f"starting the site: {site.start}")
            server = start_server(site.start, repo, server_log)
        status = wait_ready(site.url, site.ready_s if site.start else min(site.ready_s, 30),
                            server)
        if status is None:
            why = (f"the server started by `{site.start}` never answered {site.url} within "
                   f"{site.ready_s} s" + (f" (its output is in {server_log})" if server_log else "")
                   if site.start else f"{site.url} did not answer")
            return Pass(not_tested=[f"no page was checked in a browser: {why}"],
                        facts={"skipped": why})
        with sync_playwright() as pw:
            browser, engine = _launch(pw)
            if browser is None:
                return Pass(not_tested=[f"no page was checked in a browser: no browser could be "
                                        f"launched ({engine})"],
                            facts={"skipped": "no browser"})
            run = _Run(site, repo, log, browser, engine)
            phases: dict = {}
            try:
                # The cheap whole-site checks before the phone pass, which scrolls every page:
                # a budget that runs out costs the last pages of one check, not three checks
                # (a Next.js site, 2026-11-14: 900 s ran out before links, images and no-JS forms).
                for name, phase in (("crawl", run.crawl), ("links", run.links),
                                    ("social-image", run.social), ("get-form", run.no_js),
                                    ("phone", run.phone)):
                    if run.wall:
                        break
                    began = time.monotonic()
                    phase()
                    phases[name] = round(time.monotonic() - began, 1)
                run.report_hidden()
            finally:
                run.summarise()
                browser.close()
            run.result.facts["seconds"] = round(time.monotonic() - started, 1)
            run.result.facts["phase_seconds"] = phases
            return run.result
    finally:
        stop_server(server)


# ── verdict-browse ────────────────────────────────────────────────────────────

def _print(result: Pass) -> None:
    facts = result.facts
    pages = facts.get("pages") or []
    print(f"{ENGINE}: {len(pages)} page(s) in {facts.get('browser', 'no browser')}, "
          f"{facts.get('seconds', 0)} s; model calls: 0")
    for n, f in enumerate(result.findings, 1):
        print(f"  B-{n} {f['severity']}: {f['title']}")
        print(f"      {f['evidence'][0][:300]}")
    if not result.findings:
        print("  no findings")
    print("  not tested:")
    for line in result.not_tested:
        print(f"    - {line}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=ENGINE, description="Check a website in a real browser: measured, GET only, no model.")
    ap.add_argument("url", help="the page to start from; {port} is replaced by a free port")
    ap.add_argument("--start", default=None, metavar="CMD",
                    help="a command that serves the site on this machine (run from --repo)")
    ap.add_argument("--repo", type=Path, default=None,
                    help="the site's repository: findings cite the file that serves each page")
    ap.add_argument("--pages", default="", help="more paths to visit, comma-separated")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--ready-s", type=int, default=READY_S)
    ap.add_argument("--budget-s", type=int, default=BUDGET_S)
    ap.add_argument("--only", default="", help=f"checks to run, comma-separated: {', '.join(CHECKS)}")
    ap.add_argument("--skip", default="", help="path prefixes never to visit, comma-separated")
    ap.add_argument("--json", type=Path, default=None, help="write the whole result here")
    args = ap.parse_args(argv)
    try:
        site = make_site(args.url, args.start, _list(args.pages), max_pages=args.max_pages,
                         ready_s=args.ready_s, budget_s=args.budget_s,
                         checks=_list(args.only) or None, skip=_list(args.skip))
    except SiteError as exc:
        print(f"{ENGINE}: {exc}", file=sys.stderr)
        return 2
    if sync_playwright is None:
        print(f"{ENGINE}: {NO_PLAYWRIGHT}", file=sys.stderr)
        return 3
    result = browse(site, repo=args.repo)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"findings": result.findings,
                                         "not_tested": result.not_tested,
                                         "facts": result.facts,
                                         "measured": sorted(map(list, result.measured))},
                                        indent=1, ensure_ascii=False), encoding="utf-8")
    _print(result)
    if result.facts.get("skipped"):
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
