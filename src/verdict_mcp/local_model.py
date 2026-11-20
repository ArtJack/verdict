"""The model behind the gateway, as a subroutine of the local engine: one call that
answers in JSON, the liveness probe, and the JSON pulled out of an answer.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request


# ── the model, as a subroutine ────────────────────────────────────────────────


DEFAULT_TIMEOUT_S = 900


# The window each question asks for. Ollama serves every model at 4,096 tokens unless told
# otherwise, and past that it keeps only the END of the prompt: the instructions go first,
# `/no_think` with them, and the model thinks through its whole budget and answers nothing
# or invents something. Measured 2026-09-17 through the author's gateway, one ~6k-token
# prompt with a code word on its first line: at the default it arrived as 2,050 tokens and
# the model answered "0126"; asked with `num_ctx: 8192` it arrived whole (5,943 tokens), the
# answer was right, and it came back in 49 seconds instead of 137. Sent on the request, so it
# needs no change on anyone's server; `--num-ctx 0` leaves the server's default alone.
DEFAULT_NUM_CTX = 8192


LIVELINESS_PATH = "/health/liveliness"


class Model:
    """One bounded question, one JSON answer. No conversation, no accumulation.

    `/no_think` is prepended for the Qwen family, which otherwise spends its whole
    output budget reasoning and returns an empty text block — measured, not assumed.
    """

    def __init__(self, name: str, base_url: str, token: str, timeout_s=DEFAULT_TIMEOUT_S,
                 num_ctx: int = DEFAULT_NUM_CTX):
        self.name, self.base_url, self.token, self.timeout_s = name, base_url, token, timeout_s
        self.num_ctx = int(num_ctx or 0)
        self.calls, self.input_tokens, self.output_tokens, self.retries = 0, 0, 0, 0
        # A transport failure and an unparseable reply are different facts, and
        # `retries` counted only the second. A night where the gateway died
        # halfway through therefore reported "0 retries" beside a judgment built
        # from half the questions — which reads as a clean run. Counted apart,
        # and both land in `last_run.local`.
        self.errors, self.answered, self.unanswered = 0, 0, 0

    def ask(self, prompt: str, max_tokens: int = 1200) -> str:
        body = {"model": self.name, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": "/no_think\n" + prompt}]}
        if self.num_ctx:
            body["num_ctx"] = self.num_ctx
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/v1/messages", data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                doc = json.load(resp)
        except urllib.error.HTTPError as exc:
            # A gateway in front of something that is not Ollama may refuse a parameter it
            # does not know. That is a fact about the server, not a failed question: ask
            # again without the window, once, and say what that costs.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:       # noqa: BLE001 — the body is a courtesy, not evidence
                pass
            if self.num_ctx and exc.code in (400, 422) and "num_ctx" in detail:
                print(f"verdict-local: the gateway refused num_ctx ({exc.code}); asking without "
                      "it — a server that keeps its default window will cut long questions "
                      "from the front", file=sys.stderr)
                self.num_ctx = 0
                return self.ask(prompt, max_tokens)
            raise
        self.calls += 1
        usage = doc.get("usage") or {}
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        return "".join(b.get("text") or "" for b in doc.get("content", [])
                       if b.get("type") == "text")

    def ask_json(self, prompt: str, max_tokens: int = 1200) -> dict | None:
        """The answer as JSON, or None. One retry with a blunter instruction, because
        a small model's first answer is often prose with JSON inside it."""
        for attempt in (1, 2, 3):
            try:
                text = self.ask(prompt if attempt == 1 else
                                prompt + "\n\nReturn ONLY the JSON object, starting with "
                                         "{ and ending with }. No prose, no explanation.",
                                max_tokens)
            except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
                self.errors += 1
                self.unanswered += 1
                return None
            doc = extract_json(text)
            if doc is not None:
                self.answered += 1
                return doc
            self.retries += 1
        self.unanswered += 1
        return None


def gateway_alive(base_url: str, token: str | None = None, timeout_s: float = 10.0) -> tuple:
    """Is anything listening → (alive, what the endpoint said).

    Asked BEFORE the suite runs, never after. A gateway discovered dead at the
    first question has already cost a full suite run and left a run marker
    behind announcing a run in progress; asked first it costs one HTTP round
    trip, and the night is recorded honestly as one where no model was
    available rather than as one that judged nothing and said `pass`.
    """
    url = base_url.rstrip("/") + LIVELINESS_PATH
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode() or 0)
    except urllib.error.HTTPError as exc:
        # An HTTP error is still an answer: something is listening. 401 means a
        # credential problem, not a dead endpoint, and calling that "unreachable"
        # sends the operator to the wrong half of the system.
        return 200 <= int(exc.code) < 300, f"{url} answered {exc.code}"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return False, f"{url} is unreachable: {str(exc)[:160]}"
    return 200 <= code < 300, f"{url} answered {code}"


def extract_json(text: str) -> dict | None:
    """The first JSON object in a reply — a small model wraps it in prose, fences it,
    or both, and refusing that costs a call for nothing."""
    if not text:
        return None
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            doc, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            return doc
    return None
