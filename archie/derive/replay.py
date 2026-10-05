"""Re-apply what the user told Archie about people when the remember logic changes
(spec: durable-fixes §1c). journal/told.md is never changed; which version last applied each
line is kept in state/told_applied.yaml. Only person tellings are replayed, in told order,
so a later correction still wins."""

from __future__ import annotations

import hashlib
import re

import yaml

from archie.ask.context import Ctx
from archie.derive.failures import Failures
from archie.derive.versions import stamp
from archie.llm.backend import LLMError
from archie.store.files import atomic_write

STATE = "state/told_applied.yaml"
LINE = re.compile(r'^- (\d{4}-\d\d-\d\d) · "(.+)" → (.+)$')


def remember_version() -> str:
    from archie.ask.remember import REMEMBER_VERSION, SHAPE
    from archie.llm.prompts import load_prompt

    return stamp("remember", REMEMBER_VERSION, load_prompt("remember"), repr(SHAPE))


def told_lines(home) -> list[tuple[str, str, str]]:
    """(key, words, result) for each line Archie wrote; anything else in the file is skipped."""
    from archie.ask.tell import TOLD

    path = home / TOLD
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line.strip())
        if m:
            day, text, result = m.groups()
            out.append((hashlib.sha1(f"{day}|{text}".encode()).hexdigest()[:12], text, result))
    return out


def _replayable(result: str) -> bool:
    from archie.ask.tell import SAVED_ONLY

    return result == SAVED_ONLY or result.startswith("remembered:")


def replay_tellings(ctx: Ctx) -> list[str]:
    from archie.ask.remember import remember_people

    version = remember_version()
    path = ctx.home / STATE
    state = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    applied = dict(state.get("applied") or {})
    failures = Failures(ctx.home)
    changed: list[str] = []
    for key, text, result in told_lines(ctx.home):
        if not _replayable(result) or applied.get(key) == version or failures.gave_up(f"told:{key}", version):
            continue
        try:
            lines = remember_people(ctx, text, changed_only=True)
        except LLMError as exc:
            failures.failed(f"told:{key}", version, exc)
            continue
        failures.ok(f"told:{key}")
        applied[key] = version
        changed += [x.split(":")[0].removesuffix(", new") for x in lines if not x.startswith("Which ")]
    failures.save()
    if applied != (state.get("applied") or {}):
        atomic_write(path, yaml.safe_dump({"applied": applied}, sort_keys=True))
    names = list(dict.fromkeys(changed))
    if not names:
        return []
    n = len(names)
    return [f"Re-applied {n} thing{'' if n == 1 else 's'} you told me earlier: {', '.join(names)}"]
