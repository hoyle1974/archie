"""Atomic file writes, Markdown notes with YAML frontmatter, raw JSON mirrors (DESIGN §4)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + rename so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class Note:
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as strings: times are ISO strings everywhere."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_note(text: str) -> Note:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            meta = yaml.load(text[4:end], Loader=_Loader) or {}
            return Note(meta=meta, body=text[end + 5 :])
    return Note(meta={}, body=text)


def render_note(note: Note) -> str:
    if not note.meta:
        return note.body
    head = yaml.dump(note.meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)
    return f"---\n{head}---\n{note.body}"


def read_note(path: Path) -> Note:
    return parse_note(Path(path).read_text(encoding="utf-8"))


def write_note(path: Path, note: Note) -> None:
    atomic_write(path, render_note(note))


def write_raw(path: Path, data: dict) -> None:
    """Raw source mirror: stable JSON so identical payloads give identical bytes."""
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_raw(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tombstone(path: Path, deleted_at: str) -> None:
    """Mark a raw object deleted at its source; the payload stays for old citations."""
    path = Path(path)
    data = read_raw(path) if path.exists() else {}
    data.update(deleted=True, deleted_at=deleted_at)
    write_raw(path, data)
