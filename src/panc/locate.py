"""Find where Pangram's segments start in the text the user actually gave us.

Window offsets point into the text Pangram returns, which Pangram 4 may normalize, and panc
trims the input before sending it. So the offsets can't be used on the original as-is.
"""

from __future__ import annotations

import unicodedata

from .client import Result

# Curly quotes and en/em dashes, which Pangram may straighten out.
_LOOKALIKES = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)


def _fold(text: str) -> tuple[str, list[int]]:
    """Normalize text for matching, remembering which index of `text` each char came from."""
    chars: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        folded = " " if ch.isspace() else unicodedata.normalize("NFKC", ch).translate(_LOOKALIKES)
        for c in folded:
            if c == " " and chars and chars[-1] == " ":
                continue
            chars.append(c)
            origin.append(i)
    return "".join(chars), origin


def segment_starts(original: str, result: Result) -> list[int | None]:
    """Offset in `original` of each segment's first non-space character (None if not found)."""
    base = original.find(result.text) if result.text else -1
    if base != -1:
        starts: list[int | None] = []
        for w in result.windows:
            segment = result.text[w.start_index : w.end_index]
            starts.append(base + w.start_index + len(segment) - len(segment.lstrip()))
        return starts

    # Pangram changed the text somehow; find each segment by its opening words instead.
    haystack, origin = _fold(original)
    starts, cursor = [], 0
    for w in result.windows:
        opening = _fold(w.text)[0].strip()
        found = -1
        for length in (40, 12):
            if opening and (found := haystack.find(opening[:length], cursor)) != -1:
                break
        if found == -1:
            starts.append(None)
            continue
        starts.append(origin[found])
        cursor = found + 1
    return starts


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-based line and column of `offset` in `text`."""
    line_start = text.rfind("\n", 0, offset) + 1
    return text.count("\n", 0, offset) + 1, offset - line_start + 1
