"""The site's own server, when the profile starts one: waiting until it answers, starting it,
and stopping it with everything it started.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.robotparser
from pathlib import Path

try:
    from .browser_config import ENGINE
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from browser_config import ENGINE


# ── the server ────────────────────────────────────────────────────────────────


def _answers(url: str, timeout_s: float = 5.0) -> int | None:
    """The HTTP status the URL answers with, or None when nothing answers."""
    request = urllib.request.Request(url, headers={"User-Agent": ENGINE})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_ready(url: str, ready_s: int, server=None) -> int | None:
    deadline = time.monotonic() + ready_s
    while time.monotonic() < deadline:
        status = _answers(url, timeout_s=min(10.0, max(1.0, deadline - time.monotonic())))
        if status is not None and status < 500:
            return status
        if server is not None and server.poll() is not None:
            return None
        time.sleep(0.5)
    return None


def start_server(command: str, repo: Path | None, log_path: Path | None):
    """The profile's `start` command, in its own process group so the whole tree it spawns
    (npm → node) can be stopped."""
    out = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL  # noqa: SIM115
    kwargs = {"cwd": str(repo) if repo else None, "shell": True, "stdout": out,
              "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)  # noqa: S602 - the profile's own command
    process._verdict_log = out  # closed by stop_server
    return process


def stop_server(process) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                               capture_output=True, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
    finally:
        out = getattr(process, "_verdict_log", None)
        if out not in (None, subprocess.DEVNULL):
            out.close()
