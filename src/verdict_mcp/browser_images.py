"""Images, read from their headers: the size an image says it is, without decoding it.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import struct


# ── images, read from their headers ───────────────────────────────────────────


def image_size(data: bytes) -> tuple | None:
    """(width, height) from a PNG, GIF, JPEG or WebP header; None for anything else."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            i += 2
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                continue
            length = struct.unpack(">H", data[i:i + 2])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 3:i + 7])
                return width, height
            i += length
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 ":
            return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF)
        if chunk == b"VP8L":
            b = data[21:25]
            return (1 + (((b[1] & 0x3F) << 8) | b[0]),
                    1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6)))
        if chunk == b"VP8X":
            return (1 + int.from_bytes(data[24:27], "little"),
                    1 + int.from_bytes(data[27:30], "little"))
    return None
