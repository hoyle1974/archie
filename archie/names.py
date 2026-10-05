"""One way to compare names (spec: durable-fixes §4): case, curly quotes, edge punctuation
and possessives ("Workperson's", "Workpersons") don't stop a name from matching."""

from __future__ import annotations

_QUOTES = str.maketrans({"’": "'", "‘": "'"})
_EDGE = ".,;:!?\"()[]{}-"


def name_key(word: str) -> str:
    w = word.translate(_QUOTES).lower().strip(_EDGE)
    if w.endswith("'s"):
        w = w[:-2]
    elif w.endswith("'"):
        w = w[:-1]
    return w.strip(_EDGE + "'")


def name_forms(word: str) -> set[str]:
    """The word as heard, its key, and the key without a trailing s ("workpersons" -> "workperson")."""
    key = name_key(word)
    forms = {word.translate(_QUOTES).lower().strip(".'-"), key}
    if key.endswith("s") and len(key) > 3 and " " not in key:
        forms.add(key[:-1])
    return {f for f in forms if f}
