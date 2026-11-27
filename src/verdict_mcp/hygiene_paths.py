"""What a path is: a test, a script, a generated file, or an encrypted one.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from .hygiene_const import (CODE_SUFFIXES, _CODE_CLASS, _DOC_SUFFIXES, _MINIFIED, _SCRIPT_DIRS,
                                _TEST_DIRS, _VENDOR_DIRS)
    from .hygiene_patterns import _ENCRYPTED_INNER, _ENCRYPTED_LAST, _SOPS_MAC
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import (CODE_SUFFIXES, _CODE_CLASS, _DOC_SUFFIXES, _MINIFIED, _SCRIPT_DIRS,
                               _TEST_DIRS, _VENDOR_DIRS)
    from hygiene_patterns import _ENCRYPTED_INNER, _ENCRYPTED_LAST, _SOPS_MAC


def is_test_path(rel: str) -> bool:
    p = rel.replace("\\", "/").lower()
    if any(d in _TEST_DIRS for d in p.split("/")[:-1]):
        return True
    return re.search(r"(?:^|/)(?:test_[^/]*\.py|[^/]*_tests?\.py|tests?\.py|conftest\.py"
                     r"|[^/]*\.(?:test|spec|cy)\.[cm]?[jt]sx?|setuptests\.[cm]?[jt]sx?"
                     r"|(?:jest|vitest)\.setup\.[^/]*)$", p) is not None


def _is_script_path(rel: str) -> bool:
    parts = rel.lower().split("/")
    return parts[0] in _SCRIPT_DIRS or ".config." in parts[-1]


def _generated(rel: str) -> bool:
    """Minified or vendored: code nobody here wrote, so its junk is nobody's here."""
    parts = rel.lower().split("/")
    return _MINIFIED.search(parts[-1]) is not None or any(d in _VENDOR_DIRS for d in parts[:-1])


def _encrypted_name(name: str) -> bool:
    """`.env.sops`, `secrets.enc.yaml`, `.env.vault` — but `vault.py` is code. A name
    with no dot at all (Ansible's `group_vars/all/vault`) is left to its content, so
    a plaintext file that only sounds encrypted is still read."""
    parts = name.lower().split(".")
    if len(parts) < 2 or "." + parts[-1] in CODE_SUFFIXES:
        return False
    return parts[-1] in _ENCRYPTED_LAST or any(p in _ENCRYPTED_INNER for p in parts[:-1])


def _encrypted_text(name: str, text: str) -> bool:
    """SOPS (its MAC in the file's own metadata), Ansible Vault, PGP or age content.
    Source code and documents are never such a payload: a scanner, its tests, a
    SOPS helper or a page that explains SOPS may quote a marker, and quoting one
    must not hide every key in the file."""
    suffix = Path(name).suffix.lower()
    if suffix in _CODE_CLASS or suffix in _DOC_SUFFIXES:
        return False
    head = text[:4096].lstrip()
    return (_SOPS_MAC.search(text) is not None or "-----BEGIN PGP MESSAGE-----" in text
            or head.startswith(("$ANSIBLE_VAULT;", "age-encryption.org/v1")))
