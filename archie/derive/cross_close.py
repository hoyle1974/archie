"""Close loops across channels (DESIGN §6.3): an email ask can be finished by a PR review,
a commit, a ticket change, a doc edit or meeting notes.

Candidates are the user's own activity since the loop opened that shares words with it;
the fast model confirms with a verified quote. Strong -> done; weak -> maybe_done (the
user is asked). Each loop is re-checked only when there's newer activity.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from archie.activity import my_activity
from archie.ask.context import Ctx
from archie.derive.loops import OPEN, _history, load_loops, save_loop
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, check_quote
from archie.store.files import atomic_write

STOP = {"the", "a", "an", "to", "for", "and", "of", "on", "in", "with", "by", "your", "you", "my", "me", "about",
        "send", "reply", "respond", "please", "review", "check", "get", "make", "do", "this", "that", "from", "it"}
SCHEMA = {
    "title": "loops_cross",
    "type": "object",
    "properties": {"done": {"type": "boolean"}, "strength": {"type": "string", "enum": ["strong", "weak"]},
                   "ref": {"type": "integer"}, "quote": {"type": "string"}},
    "required": ["done", "strength", "ref", "quote"],
    "additionalProperties": False,
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def _check(ctx: Ctx, lp, checked: dict) -> str | None:
    """Check one loop; returns the newest candidate time seen (to record), or None if skipped."""
    m = lp.meta
    start = datetime.fromisoformat(m["created_at"])
    own_thread = {s.get("file") for s in m.get("sources") or []}
    want = _words(m.get("summary", ""))
    cands = [i for i in my_activity(ctx, start, ctx.now)
             if i.path not in own_thread and len(want & _words(i.title + " " + i.quote)) >= 1]
    if not cands or cands[-1].when <= checked.get(lp.loop_id, ""):
        return None
    newest = max(i.when for i in cands)
    cands = sorted(cands, key=lambda i: -len(want & _words(i.title)))[:5]
    packet = Packet()
    for i in cands:
        text = next((c["text"] for c in ctx.index.chunks_of(i.path) if c["chunk_id"] == i.chunk), i.title)
        packet.add(i.path, i.chunk, text, label=ctx.index.label_of(i.path, i.chunk), ts=i.when)
    system = load_prompt("loops_cross", me_name=ctx.me.name or "the user")
    user = f"Open item: {m.get('summary')} (with {m.get('counterpart_name')})\n\nLater activity:\n\n{packet.render()}"
    try:
        out = ctx.backend.complete(system, user, SCHEMA, tier="fast")
    except LLMError:
        return None
    cite = check_quote(packet, int(out.get("ref", 0)), out.get("quote", "")) if out.get("done") else None
    if cite is not None:
        m["status"] = "done" if out.get("strength") == "strong" else "maybe_done"
        m["closed_by"] = {"file": cite.path, "chunk": cite.chunk_id, "quote": cite.quote}
        verdict = "closed" if m["status"] == "done" else "probably done (asking you)"
        _history(lp, f"{ctx.now.date().isoformat()} {verdict}: {cite.label}")
        save_loop(ctx.home, lp)
    return newest


def close_across_channels(ctx: Ctx, paths: list[Path]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    state_file = ctx.home / "state/cross_checked.yaml"
    checked = (yaml.safe_load(state_file.read_text()) or {}) if state_file.exists() else {}
    loops = [lp for lp in load_loops(ctx.home)
             if lp.meta.get("status") in OPEN and lp.meta.get("kind") != "waiting_on"]
    workers = max(1, int(ctx.config["llm"].get("parallel", 1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda lp: _check(ctx, lp, checked), loops))
    updated = {lp.loop_id: r for lp, r in zip(loops, results) if r}
    if updated:
        checked.update(updated)
        atomic_write(state_file, yaml.safe_dump(checked, sort_keys=True))
