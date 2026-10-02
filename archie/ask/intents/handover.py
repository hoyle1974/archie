"""`handover`: a project handover document (Vignette G).

Retrieval in code: hybrid search on the project's name and aliases (from projects/<slug>.md
if the user keeps one), plus open loops that mention it. People involved are counted by
code. The LLM writes the cited sections; the result is saved under projects/."""

from __future__ import annotations

import re
from collections import Counter

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.intents.loops import _claim, _line
from archie.ask.render import render
from archie.ask.synthesize import synthesize
from archie.derive.loops import load_loops, rank
from archie.derive.people import PeopleDirectory, slug
from archie.index.search import search
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet
from archie.store.files import Note, read_note, write_note


def _project(question: str, params: dict) -> str:
    if params.get("topic"):
        return params["topic"].strip()
    m = re.search(r"handover (?:doc(?:ument)? )?for (?:the )?(.+?)(?: project)?[?.]?$", question, re.I)
    return (m.group(1) if m else question).strip()


@intent("handover")
def handover_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    name = _project(question, params)
    pslug = slug(name).replace("_", "-")
    proj = ctx.home / f"projects/{pslug}.md"
    aliases = [name] + list(read_note(proj).meta.get("aliases") or [] if proj.exists() else [])
    packet = Packet()
    for a in aliases:
        for h in search(ctx.index, a, k=25):
            if h.source not in ("briefings", "loops", "journal", "projects"):
                packet.add(h.path, h.chunk_id, h.text, label=h.label, ts=h.ts)
    if not packet.items:
        return Answer(plain=f"I couldn't find anything about {name}.")
    directory = PeopleDirectory.load(ctx.home)
    by_id = {i: e for e in directory.meta for i in directory.identifiers(e)}
    counts = Counter()
    for it in packet.items:
        row = ctx.index.conn.execute("SELECT people FROM chunks WHERE path = ? AND chunk_id = ?",
                                     (it.path, it.chunk_id)).fetchone()
        import json

        for pid in json.loads(row[0] if row else "[]"):
            if pid in by_id:
                counts[by_id[pid]] += 1
    words = {w for w in re.findall(r"\w{4,}", name.lower())}
    loops = [r for r in rank(load_loops(ctx.home), ctx.now, ctx.config)
             if words & set(re.findall(r"\w{4,}", str(r.loop.meta.get("summary", "")).lower()))]
    answer = synthesize(ctx, f"Write a handover for {name}", packet,
                        load_prompt("handover_hint", project=name), tier="strong")
    answer.title = f"Handover: {name}"
    if counts:
        answer.sections.insert(0, Section("People", lines=[f"{directory.name(e)} ({n} mentions)"
                                                          for e, n in counts.most_common(8)]))
    if loops:
        answer.sections.append(Section("Open loops", items=[_claim(ctx, r, _line(r)) for r in loops[:10]]))
    local = ctx.now.astimezone()
    path = ctx.home / f"projects/{pslug}-handover-{local:%Y-%m-%d}.md"
    write_note(path, Note(meta={"project": name, "written": ctx.now.isoformat()}, body=render(answer, sources=True) + "\n"))
    answer.notes.append(f"Saved to {path.relative_to(ctx.home.root)}.")
    return answer
