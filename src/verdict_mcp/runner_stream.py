"""Running the tester's session with its output streamed, and the heartbeat that says a long,
quiet run is still alive.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time


def _heartbeat_s() -> int:
    try:
        return max(1, int(os.environ.get("VERDICT_HEARTBEAT_S", "60")))
    except ValueError:
        return 60


def _run_streaming(cmd, repo, env, timeout_s):
    """Run the claude CLI, echoing its output live, with a heartbeat.

    The previous shape — `subprocess.run(capture_output=True)` — was a black
    box: the nightly log stayed empty for the whole run, a killed parent left
    no trace at all, and the first external user reported being bitten by
    exactly that, twice. Lines are echoed to stderr as they arrive (so a
    redirected log grows in real time and survives a kill mid-run), and when
    the child says nothing for VERDICT_HEARTBEAT_S seconds (default 60) a
    heartbeat line says the run is alive and how long it has been quiet.

    Returns (returncode, combined_output); returncode is None on timeout.
    """
    proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()

    def _pump():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=_pump, daemon=True).start()
    buf = []
    start = last_output = time.monotonic()
    heartbeat = _heartbeat_s()
    while True:
        remaining = timeout_s - (time.monotonic() - start)
        if remaining <= 0:
            proc.kill()
            proc.wait()
            return None, "".join(buf)
        try:
            item = lines.get(timeout=min(heartbeat, remaining))
        except queue.Empty:
            quiet = int(time.monotonic() - last_output)
            elapsed = int((time.monotonic() - start) // 60)
            print(f"verdict-run: still running — {elapsed}m elapsed, "
                  f"no output for {quiet}s", file=sys.stderr, flush=True)
            continue
        if item is None:
            break
        buf.append(item)
        last_output = time.monotonic()
        sys.stderr.write(item)
        sys.stderr.flush()
    return proc.wait(), "".join(buf)
