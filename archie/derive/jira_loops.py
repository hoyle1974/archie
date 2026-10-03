"""Jira asks: a NEW comment that @mentions the user goes through the same verified loop
extraction as email (asked_of_me only: the comment must be someone else's). The user's
own later comments can close it, checked like an email reply."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import yaml

from archie.ask.context import Ctx
from archie.derive.dates import due_in
from archie.derive.loops import (CLOSE_SHAPE, EXTRACT_SHAPE, OPEN, Loop, _duplicate, _history, load_loops,
                                 save_loop)
from archie.derive.people import PeopleDirectory, slug
from archie.index.chunk import chunk_file
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, check_quote
from archie.store.files import Note, atomic_write, read_raw


def _packet(rel: str, text: str, new: set[int]) -> Packet:
    p = Packet()
    for i, c in enumerate(chunk_file(rel, text)):
        p.add(c.path, c.chunk_id, c.text, label=f"{c.label}{' NEW' if i in new else ''}")
    return p


def derive_jira_loops(ctx: Ctx, paths: list[Path]) -> None:
    seen_file = ctx.home / "state/jira_seen.yaml"
    seen = (yaml.safe_load(seen_file.read_text()) or {}) if seen_file.exists() else {}
    directory = PeopleDirectory.load(ctx.home)
    loops = load_loops(ctx.home)
    me = ctx.me.name or "the user"
    changed = False
    for path in sorted(paths):
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/jira/") or not Path(path).exists():
            continue
        data = read_raw(path)
        key = data.get("key", Path(path).stem)
        comments = data.get("comments") or []
        new = {i for i, c in enumerate(comments) if (c.get("date") or "") > seen.get(key, "")}
        if data.get("deleted") or not new:
            continue
        packet = _packet(rel, Path(path).read_text(), {i + 1 for i in new})  # chunk 0 is the description
        mine_new = {i + 2 for i in new if comments[i].get("from_me")}
        asks_new = {i + 2 for i in new if comments[i].get("mentions_me") and not comments[i].get("from_me")}
        here = [lp for lp in loops if lp.meta.get("thread") == rel and lp.meta.get("status") in OPEN]
        try:
            if here and mine_new:
                listing = "\n".join(f"{n}. ({lp.meta['kind']}) {lp.meta['summary']}" for n, lp in enumerate(here, 1))
                out = ctx.backend.complete(load_prompt("loops_close", me_name=me),
                                           f"Open loops:\n{listing}\n\nThread (NEW messages are marked):\n\n{packet.render()}",
                                           CLOSE_SHAPE, tier="fast")
                for upd in out.get("updates") or []:
                    n, ref = int(upd.get("loop", 0)), int(upd.get("ref", 0))
                    cite = check_quote(packet, ref, upd.get("quote", "")) if ref in mine_new else None
                    if upd.get("resolved") and cite and 1 <= n <= len(here):
                        lp = here[n - 1]
                        lp.meta["status"], lp.meta["closed_by"] = "done", {"file": rel, "chunk": cite.chunk_id,
                                                                           "quote": cite.quote}
                        _history(lp, f"{ctx.now.date().isoformat()} closed by your comment")
                        save_loop(ctx.home, lp)
            if asks_new:
                system = load_prompt("loops_extract", me_name=me)
                out = ctx.backend.complete(system, f"Thread:\n\n{packet.render()}", EXTRACT_SHAPE, tier="fast")
                for c in out.get("loops") or []:
                    ref = int(c.get("ref", 0))
                    cite = check_quote(packet, ref, c.get("quote", "")) if ref in asks_new else None
                    if cite is None or c.get("kind") != "asked_of_me":
                        continue
                    author = comments[ref - 2]["author"]
                    eid = directory.by_email(author.get("email") or "") if author.get("email") else None
                    cp_id, cp_name = (eid, directory.name(eid)) if eid else (f"jira:{author.get('id')}", author.get("name"))
                    source = {"file": rel, "chunk": cite.chunk_id, "quote": cite.quote}
                    if _duplicate(source, "asked_of_me", loops):
                        continue
                    when = datetime.fromisoformat(comments[ref - 2]["date"]).astimezone()
                    h = hashlib.sha1(f"{rel}|{ref}|{cite.quote}".encode()).hexdigest()[:6]
                    loop_id = f"loop-{when:%Y%m%d-%H%M}-{slug(cp_name)[:24]}-{h}"
                    meta = {"loop_id": loop_id, "kind": "asked_of_me", "status": "open", "counterpart": cp_id,
                            "counterpart_name": cp_name, "summary": c.get("summary", "").strip() or f"Reply on {key}",
                            "created_at": when.isoformat(), "due": due_in(cite.quote, when), "snoozed_until": None, "thread": rel,
                            "addressed": "to", "sources": [source], "closed_by": None}
                    lp = Loop(loop_id, f"loops/{when:%Y}/{loop_id}.md", Note(meta=meta, body=""))
                    _history(lp, f"{when:%Y-%m-%d %H:%M} mentioned on {key}")
                    save_loop(ctx.home, lp)
                    loops.append(lp)
        except LLMError:
            continue
        seen[key] = max(c.get("date") or "" for c in comments)
        changed = True
    if changed:
        atomic_write(seen_file, yaml.safe_dump(seen, sort_keys=True))
