"""A small website with one seeded defect per browser check and a clean twin beside each.

Served from a temporary directory by a stdlib server that records every request, so a test
can assert what the browser pass found, what it did not flag, and what it never sent: no write
reaches the server, no stateful link is followed.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import struct
import threading
import zlib
from pathlib import Path


def png(width: int, height: int) -> bytes:
    """A grey PNG of the given size, from the standard library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def page(title: str, body: str, head: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title>{head}</head><body>{body}</body></html>")


LOREM = ("Every truck that crosses a state line files a quarterly fuel tax return, and every "
         "return starts with the miles and the gallons. ")

PAGES = {
    # ── autofill-trap ──
    "trap.html": page("Trap", """
<form method="post" action="/contact">
  <div aria-hidden="true" style="position:absolute;left:-9999px;width:0;height:0;overflow:hidden">
    <label>Company <input type="text" name="company" tabindex="-1" autocomplete="off"></label>
  </div>
  <label for="name">Name</label> <input id="name" name="name" autocomplete="name">
  <label for="email">Email</label> <input id="email" name="email" type="email" autocomplete="email">
  <button>Send</button>
</form>"""),
    "trap-ok.html": page("Trap ok", """
<form method="post" action="/contact">
  <div style="display:none"><label>Company <input type="text" name="company" tabindex="-1"></label></div>
  <label for="name">Name</label> <input id="name" name="name" autocomplete="name">
  <label for="email">Email</label> <input id="email" name="email" type="email" autocomplete="email">
  <button>Send</button>
</form>"""),
    # ── phone-width ──
    "wide.html": page("Wide", '<h1>Rates</h1><div class="table" style="width:640px">A wide '
                              'table of rates</div>'),
    "narrow.html": page("Narrow", '<h1>Rates</h1><div style="max-width:100%">A table of rates'
                                  '</div>'),
    # ── long-input, keyboard and focus on a file picker ──
    "upload.html": page("Upload", """
<form method="post" action="/upload">
<label id="drop" role="button" tabindex="0" style="display:block;width:300px;padding:8px;border:1px solid #888">
  Choose a file
  <input type="file" id="f" name="files" accept=".pdf,.csv" style="position:absolute;width:1px;height:1px;opacity:0;overflow:hidden">
</label>
<div id="chosen" style="white-space:nowrap"></div>
</form>
<script>
  const f = document.getElementById('f'), chosen = document.getElementById('chosen');
  f.addEventListener('change', () => { chosen.textContent = f.files[0] ? f.files[0].name : ''; });
</script>"""),
    "upload-ok.html": page("Upload ok", """
<style>#drop:focus-within, #drop:focus-visible { outline: 3px solid #1a5fb4; }</style>
<form method="post" action="/upload">
<label id="drop" role="button" tabindex="0" style="display:block;width:300px;padding:8px;border:1px solid #888">
  Choose a file
  <input type="file" id="f" name="files" accept=".pdf,.csv" style="position:absolute;width:1px;height:1px;opacity:0;overflow:hidden">
</label>
<div id="chosen" style="overflow-wrap:anywhere"></div>
</form>
<script>
  const f = document.getElementById('f'), chosen = document.getElementById('chosen');
  const drop = document.getElementById('drop');
  f.addEventListener('change', () => { chosen.textContent = f.files[0] ? f.files[0].name : ''; });
  drop.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); f.click(); }
  });
</script>"""),
    # ── ios-zoom ──
    "zoom.html": page("Zoom", '<style>input { font-size: 14px }</style><form method="post">'
                              '<label for="q1">Your name</label><input id="q1" name="fullname">'
                              '</form>'),
    "zoom-ok.html": page("Zoom ok", '<style>input { font-size: 16px }</style><form method="post">'
                                    '<label for="q1">Your name</label><input id="q1" name="fullname">'
                                    '</form>'),
    # ── hidden-at-load ──
    "reveal.html": page("Reveal", """
<style>.reveal { visibility: hidden; opacity: 0; min-height: 900px }
       .reveal.on { visibility: visible; opacity: 1 }</style>
<h1>Fuel tax, done</h1><p>""" + LOREM + "</p>"
        + "".join(f'<section class="reveal"><h2>Part {n}</h2><p>{LOREM * 3}</p>'
                  f'<a href="index.html">Back {n}</a></section>' for n in range(1, 5)) + """
<script>
  const io = new IntersectionObserver((es) => es.forEach(e => { if (e.isIntersecting) e.target.classList.add('on'); }));
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));
</script>"""),
    "reveal-ok.html": page("Reveal ok", """
<style>.reveal { opacity: 0; min-height: 900px } .reveal.on { opacity: 1 }</style>
<h1>Fuel tax, done</h1><p>""" + LOREM + "</p>"
        + "".join(f'<section class="reveal"><h2>Part {n}</h2><p>{LOREM * 3}</p></section>'
                  for n in range(1, 5)) + """
<script>
  const io = new IntersectionObserver((es) => es.forEach(e => { if (e.isIntersecting) e.target.classList.add('on'); }));
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));
</script>"""),
    # ── focus-visible ──
    "focus.html": page("Focus", '<style>#go:focus { outline: none }</style>'
                                '<p>Ready?</p><button id="go">Start the return</button>'),
    "focus-ok.html": page("Focus ok", '<p>Ready?</p><button id="go2">Start the return</button>'),
    # ── keyboard ──
    "keys.html": page("Keys", """
<div id="toggle" role="button" tabindex="0">Show the rates</div><p id="more" hidden>Rates.</p>
<script>
  document.getElementById('toggle').addEventListener('click', () => {
    const m = document.getElementById('more'); m.hidden = !m.hidden; });
</script>"""),
    "keys-ok.html": page("Keys ok", """
<div id="toggle2" role="button" tabindex="0">Show the rates</div><p id="more" hidden>Rates.</p>
<script>
  const t = document.getElementById('toggle2');
  t.addEventListener('click', () => { const m = document.getElementById('more'); m.hidden = !m.hidden; });
  t.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); t.click(); } });
</script>"""),
    # ── get-form ──
    "getform.html": page("Get form", """
<form id="contact"><label for="e">Email</label><input id="e" name="email" type="email">
<label for="m">Message</label><textarea id="m" name="message"></textarea><button>Send</button></form>
<script>document.getElementById('contact').addEventListener('submit', (e) => e.preventDefault());</script>"""),
    "getform-ok.html": page("Get form ok", """
<form method="post" action="/contact"><label for="e">Email</label><input id="e" name="email" type="email">
<label for="m">Message</label><textarea id="m" name="message"></textarea><button>Send</button></form>"""),
    # ── social-image ──
    "og.html": page("Og", '<p>Share me.</p><img src="img/missing.png" alt="">',
                    head='<meta property="og:image" content="/img/og.png">'
                         '<meta property="og:image:width" content="1200">'
                         '<meta property="og:image:height" content="630">'),
    "og-ok.html": page("Og ok", "<p>Share me too.</p>",
                       head='<meta property="og:image" content="/img/og-ok.png">'
                            '<meta property="og:image:width" content="1200">'
                            '<meta property="og:image:height" content="630">'),
    # ── the rules: no write, no third party, no stateful link ──
    "beacon.html": page("Beacon", """
<p>Analytics.</p><script src="https://third-party.invalid/tag.js"></script>
<script>fetch('/api/track', {method: 'POST', body: '{}'}).catch(() => {});</script>
<a href="/logout">Log out</a>"""),
}

INDEX = page("Home", """
<form role="search" action="/search"><input name="q" aria-label="Search"></form>
<nav>""" + "".join(f'<a href="{name}">{name}</a> ' for name in PAGES) + """
<a href="missing.html">An old page</a></nav>""")

SEEDED = {
    "autofill-trap": ["/trap.html"],
    "phone-width": ["/wide.html"],
    "long-input": ["/upload.html"],
    "ios-zoom": ["/zoom.html"],
    "hidden-at-load": ["/reveal.html"],
    "focus-visible": ["/focus.html", "/upload.html"],
    "keyboard": ["/keys.html", "/upload.html"],
    "get-form": ["/getform.html"],
    "social-image": ["/og.html"],
    "links": ["/index.html", "/og.html"],
}


def build(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    for name, html in PAGES.items():
        (root / name).write_text(html, encoding="utf-8")
    (root / "img").mkdir(exist_ok=True)
    (root / "img" / "og.png").write_bytes(png(100, 50))
    (root / "img" / "og-ok.png").write_bytes(png(1200, 630))
    return root


class _Recorder(http.server.SimpleHTTPRequestHandler):
    log: list = []

    def log_message(self, *args):
        return

    def _record(self):
        self.log.append((self.command, self.path))

    def do_GET(self):
        self._record()
        super().do_GET()

    def do_HEAD(self):
        self._record()
        super().do_HEAD()

    def do_POST(self):
        self._record()
        self.send_response(200)
        self.end_headers()


@contextlib.contextmanager
def serve(root: Path):
    """Serve `root` on 127.0.0.1 → (base url, request log)."""
    log: list = []
    handler = type("Recorder", (_Recorder,), {"log": log})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             functools.partial(handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", log
    finally:
        server.shutdown()
        server.server_close()
