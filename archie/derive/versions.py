"""Which version of a deriver's logic produced something (spec: durable-fixes §1a). When the
stamp changes, the derivation is redone from the files."""

from __future__ import annotations

import hashlib


def stamp(name: str, *parts: object) -> str:
    text = "\n".join([name, *map(str, parts)])
    return hashlib.sha256(text.encode()).hexdigest()[:12]
