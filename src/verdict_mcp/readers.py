"""One door to every reader `verdict-local` has for a language other than Python.

`languages` names a file's language and family; this module hands the file to the reader that knows
that family's shape and returns what it found in one form, a `Piece`: the lines, their name, what
holds them, the language they are written in and whether they are a function, an excerpt or a
template. A file that says it was generated, or that is not text at all, raises no question.
"""

from __future__ import annotations

try:
    from . import braces, ends, languages, regions
except ImportError:  # imported as a plain module beside small.py
    import braces
    import ends
    import languages
    import regions

Piece = regions.Piece


def read(rel: str, text: str, lines, max_lines: int) -> list | None:
    """The questions a file raises → `[Piece]`: every function in it when `lines` is None, else
    the ones its changed `lines` sit in. None for Python and for a file in no language here."""
    lang = languages.language_of(rel)
    family = languages.family_of(lang)
    if family in (None, "python"):
        return None
    if languages.looks_generated(text):
        return []
    if family == "braces":
        found = braces.functions(text, lang, max_lines) if lines is None \
            else braces.around(text, lang, lines, max_lines)
        return [Piece(name, start, end, source, context, lang, "function")
                for name, start, end, source, context in found]
    if family == "ends":
        found = ends.functions(text, lang, max_lines) if lines is None \
            else ends.around(text, lang, lines, max_lines)
        return [Piece(name, start, end, source, context, lang, "function")
                for name, start, end, source, context in found]
    if family == "regions":
        return regions.read(text, lang, lines, max_lines)
    return regions.windows(text, lang, lines, max_lines,
                           unit="template" if languages.is_template(lang) else "excerpt")
