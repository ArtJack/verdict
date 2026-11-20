"""Forms, read from the HTML a browser without JavaScript gets: which fields ask for a name,
a secret or a search, and which carry the autocomplete a person's details need.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


# ── forms, read from the HTML a browser without JavaScript gets ───────────────


_PERSONAL_NAME = re.compile(r"(?:^|[\W_])(?:e-?mail|phone|tel|mobile|cell|name|first|last|"
                            r"surname|message|comment|address|street|city|zip|postal|company|"
                            r"organi[sz]ation|ssn|dob|birth|card|cvc|cvv|iban|account|"
                            r"pass(?:word)?)(?:[\W_]|$)", re.I)


_SECRET = re.compile(r"(?:^|[\W_])(?:pass(?:word)?|card|cc-?(?:number|csc|exp)|cvc|cvv|ssn|"
                     r"iban)(?:[\W_]|$)", re.I)


_SEARCH = re.compile(r"^(?:q|query|search|s|term|keywords?|k)$", re.I)


_PERSONAL_AUTOCOMPLETE = ("name", "given-name", "family-name", "email", "tel", "street-address",
                          "address-line1", "address-line2", "postal-code", "organization",
                          "cc-number", "cc-csc", "cc-exp", "bday", "current-password",
                          "new-password", "username")


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list = []
        self._open: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._open = {"method": a.get("method", "").strip().lower() or "get",
                          "action": a.get("action", ""), "role": a.get("role", "").lower(),
                          "fields": []}
            self.forms.append(self._open)
        elif tag in ("input", "textarea", "select") and self._open is not None:
            kind = a.get("type", "text").lower() if tag == "input" else tag
            if kind in ("hidden", "submit", "button", "reset", "image", "checkbox", "radio",
                        "file"):
                return
            self._open["fields"].append({"type": kind, "name": a.get("name", ""),
                                         "id": a.get("id", ""),
                                         "autocomplete": a.get("autocomplete", "").lower()})

    def handle_endtag(self, tag):
        if tag == "form":
            self._open = None


def get_forms(html: str) -> list:
    """The forms that, without JavaScript, would put personal fields in the URL: method GET
    (the default), not a search form. → [{method, action, fields: [names], secret: bool}]"""
    parser = _Forms()
    try:
        parser.feed(html)
    except Exception:  # an HTML parser that gives up reads nothing, it does not guess
        return []
    out = []
    for form in parser.forms:
        if form["method"] != "get" or form["role"] == "search":
            continue
        fields = form["fields"]
        texts = [f for f in fields if f["type"] in ("text", "search", "")]
        if any(f["type"] == "search" for f in fields) or (
                len(fields) == 1 and texts and _SEARCH.match(texts[0]["name"] or texts[0]["id"])):
            continue
        personal, secret = [], False
        for f in fields:
            tokens = f["autocomplete"].split()
            label = f["name"] or f["id"] or f["type"]
            if (f["type"] in ("email", "tel", "password")
                    or any(t in _PERSONAL_AUTOCOMPLETE for t in tokens)
                    or _PERSONAL_NAME.search(f["name"]) or _PERSONAL_NAME.search(f["id"])):
                personal.append(label)
                secret = secret or f["type"] == "password" or bool(
                    _SECRET.search(f["name"]) or _SECRET.search(f["id"])) or any(
                    t.startswith("cc-") or t.endswith("password") for t in tokens)
        if personal:
            out.append({"method": form["method"], "action": form["action"],
                        "fields": personal, "secret": secret})
    return out
