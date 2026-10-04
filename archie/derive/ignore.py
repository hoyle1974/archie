"""Ignored senders (spec: understand-first §3.3).

One list, in config.yaml: the top-level `ignore:` entries plus the older `loops.mute`
entries. An entry is an email address or an @domain. Mail from an ignored sender makes no
open items or questions, and answers leave it out unless the question names the sender."""

from __future__ import annotations


def on_list(email: str, entries: list[str]) -> bool:
    """Exact address match, or the address is at an `@domain` entry's domain."""
    e = (email or "").lower()
    if not e:
        return False
    for x in entries or []:
        x = str(x).lower()
        if e == x or (x.startswith("@") and e.endswith(x)):
            return True
    return False
