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


def near(a: str, b: str) -> bool:
    """One typo apart ("keigth"/"workperson", "prya"/"priya", "sarha"/"sarah"): one letter added,
    dropped or changed, or two neighbours swapped. Names under 4 letters never count."""
    a, b = name_key(a), name_key(b)
    if a == b or min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))
