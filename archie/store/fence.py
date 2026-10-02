"""The fence rule (DESIGN §2.4): Archie writes only between its fence markers.

    <!-- archie:auto -->
    ...Archie-owned text...
    <!-- /archie:auto -->

Everything outside a fence belongs to the user and is preserved byte for byte. When the
markers are damaged (unclosed, duplicated), we raise rather than guess, because a wrong
guess would overwrite the user's text.
"""

from __future__ import annotations


class FenceError(ValueError):
    pass


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- archie:{name} -->\n", f"<!-- /archie:{name} -->\n"


def _span(body: str, name: str) -> tuple[int, int] | None:
    """(start, end) of the fence's inner text, or None if the fence is absent."""
    open_m, close_m = _markers(name)
    if body.count(open_m) > 1 or body.count(close_m) > 1:
        raise FenceError(f"more than one archie:{name} fence")
    start, end = body.find(open_m), body.find(close_m)
    if start == -1 and end == -1:
        return None
    if start == -1 or end == -1 or end < start:
        raise FenceError(f"archie:{name} fence is not properly opened and closed")
    return start + len(open_m), end


def get_fence(body: str, name: str = "auto") -> str | None:
    span = _span(body, name)
    return None if span is None else body[span[0] : span[1]]


def set_fence(body: str, content: str, name: str = "auto") -> str:
    if content and not content.endswith("\n"):
        content += "\n"
    span = _span(body, name)
    if span is None:
        open_m, close_m = _markers(name)
        sep = "" if not body or body.endswith("\n") else "\n"
        return f"{body}{sep}{open_m}{content}{close_m}"
    return body[: span[0]] + content + body[span[1] :]
