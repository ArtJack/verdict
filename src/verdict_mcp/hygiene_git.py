"""Reading git without a checkout: the files at HEAD and their blobs, with git's environment
kept from leaking in.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    from .hygiene_const import MAX_BYTES, _GIT_REPO_VARS
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import MAX_BYTES, _GIT_REPO_VARS


# ── reading git ───────────────────────────────────────────────────────────
class _Unavailable(Exception):
    """git cannot show a commit here; the message is the one line the caller gets."""


def _git_env() -> dict:
    """git that reads the repository asked for and never reaches for the network.
    An inherited GIT_DIR and its kin are dropped. In a partial clone a blob HEAD
    names may be absent, and git would fetch it — or sit at a credential prompt —
    for every such file; here it is a file the scan could not read instead."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_VARS}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    return env


def _head_files(repo: Path) -> list:
    """(path, oid, size) for every regular file HEAD holds, in tree order.

    Only modes 100644 and 100755 are kept: a symlink (120000) may point anywhere
    on the machine, and a submodule (160000) is another repository. Run from a
    subdirectory, git lists that subtree with paths relative to it. A blob this
    clone lacks has no size ("BAD"), which is kept as -1: its read will fail."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-l", "-z", "HEAD"],
                              capture_output=True, env=_git_env())
    except OSError as exc:
        raise _Unavailable(f"git could not run: {exc}") from None
    if proc.returncode != 0:
        said = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise _Unavailable("git could not list HEAD: "
                           + (said[0].strip() if said else f"exit status {proc.returncode}"))
    files = []
    for entry in proc.stdout.split(b"\0"):
        meta, tab, path = entry.partition(b"\t")
        fields = meta.split()
        if tab and len(fields) == 4 and fields[1] == b"blob" and fields[0] in (b"100644", b"100755"):
            size = int(fields[3]) if fields[3].isdigit() else -1
            files.append((path.decode("utf-8", "replace"), fields[2].decode("ascii"), size))
    return files


def _decode(data):
    """Text as Python itself reads it: the BOM dropped, CRLF and a lone CR made
    "\\n". The parser breaks a line at a lone CR, so the line numbers here must."""
    if data is None or b"\0" in data[:4096]:
        return None
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


class _Blobs:
    """HEAD's blobs through one long-lived `git cat-file --batch`, one object at a
    time: write the id, read the header, read exactly the size it names. Nothing is
    opened on disk, so neither a FIFO nor a link out of the tree can be reached."""

    def __init__(self, repo: Path):
        try:
            self._proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, env=_git_env())
        except OSError as exc:
            raise _Unavailable(f"git could not run: {exc}") from None
        self._kept: dict = {}
        self._broken = False

    def text(self, oid: str, size: int, keep: bool = False):
        """The blob as text, or None when it is over MAX_BYTES (never requested) or
        binary. `keep` holds it for a later path with the same content, so no blob
        is read twice in a scan."""
        if oid in self._kept:
            text = self._kept.pop(oid)
        else:
            text = None if size > MAX_BYTES else _decode(self._read(oid))
        if keep:
            self._kept[oid] = text
        return text

    def _read(self, oid: str):
        # Once an exchange breaks off halfway, the stream is out of step and every
        # later answer would belong to the wrong file: all later reads fail instead.
        if self._broken:
            raise OSError("git cat-file stopped answering earlier in this scan")
        self._broken = True
        out = self._proc.stdout
        self._proc.stdin.write(oid.encode("ascii") + b"\n")
        self._proc.stdin.flush()
        header = out.readline().split()
        if not header or header[0] != oid.encode("ascii"):
            raise OSError("git cat-file answered out of step")
        if len(header) == 2:          # "<oid> missing": still in step, but this clone lacks it
            self._broken = False
            raise OSError("the blob is not in this clone")
        size = int(header[2])
        data = out.read(size)
        if len(data) != size or out.read(1) != b"\n":
            raise OSError("git cat-file returned a short object")
        self._broken = False
        return data if header[1] == b"blob" else None

    def close(self):
        proc = self._proc
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _lines(text: str) -> list[str]:
    return [ln.rstrip("\r") for ln in text.split("\n")]
