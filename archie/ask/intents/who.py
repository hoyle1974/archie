"""`who`: who someone is and your history with them (Vignettes B, J).

Facts that code can compute (role, org, first/last contact, thread count, recent
interactions) are listed as-is; the LLM only writes the cited summary on top.
"""

from __future__ import annotations

import re

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.synthesize import synthesize
from archie.derive.people import PeopleDirectory
from archie.index.chunk import short_date
from archie.llm.verify import Packet

INSTRUCTIONS = """- Start with who this person is (role, how {me_name} knows them) if the sources say.
- Then the most recent thing they discussed or anything still open between them.
- Keep the summary to 2-3 sentences."""


def resolve(ctx: Ctx, params: dict, question: str) -> tuple[PeopleDirectory, list[str], str]:
    directory = PeopleDirectory.load(ctx.home)
    names = params.get("people") or []
    query = names[0] if names else (params.get("topic") or "")
    if not query:
        m = re.search(r"(?:who is|who's|history with)\s+([\w@.\- ]+)", question, re.I)
        query = m.group(1).strip(" ?") if m else ""
    return directory, directory.find(query) if query else [], query


def person_lines(directory: PeopleDirectory, eid: str, history: list[dict], facts: list[dict] | None = None) -> list[str]:
    meta = directory.meta[eid]
    lines = [directory.name(eid)]
    personal = [b for b in (f"Your {meta['relationship']}" if meta.get("relationship") else None,
                            meta.get("pronouns")) if b]
    if personal:
        lines.append(" · ".join(personal))
    if facts and not meta.get("role"):
        lines.append("Known for: " + "; ".join(f["text"] for f in facts[:3]))
    for key, label in (("role", "Role"), ("org", "Org")):
        if meta.get(key):
            lines.append(f"{label}: {meta[key]}")
    if meta.get("last_interaction"):
        lines.append(f"Last talked: {short_date(meta['last_interaction'])}"
                     f" · first seen {short_date(meta.get('first_seen'))}")
    threads = {h["path"] for h in history if h["source"] == "gmail"}
    if threads:
        lines.append(f"{len(threads)} email thread{'s' if len(threads) != 1 else ''} together")
    return lines


FAMILY = re.compile(r"\b(wife|husband|partner|spouse|son|daughter|child|kid|oldest|youngest|middle|mother|"
                    r"father|mom|dad|sister|brother|sibling|parent|grand\w*|aunt|uncle|cousin|niece|nephew|"
                    r"in-law|family)\b", re.I)


def family_answer(ctx: Ctx) -> Answer:
    d = PeopleDirectory.load(ctx.home)
    fam = [e for e, m in d.meta.items() if m.get("relationship") and FAMILY.search(str(m["relationship"]))]
    if not fam:
        return Answer(plain="I don't know your family yet. Tell me, e.g. \"Goodspouse is my wife\".")
    lines = []
    for e in sorted(fam, key=lambda e: d.name(e)):
        m = d.meta[e]
        extra = f" · {m['pronouns']}" if m.get("pronouns") else ""
        lines.append(f"  • {d.name(e)} (your {m['relationship']}){extra}")
    return Answer(plain="Your family, as you've told me:\n" + "\n".join(lines))


@intent("who")
def who_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    if re.search(r"\bmy (family|kids|children|parents)\b", question, re.I) or \
            re.search(r"\bfamily\b", str(params.get("topic") or ""), re.I):
        return family_answer(ctx)
    directory, matches, query = resolve(ctx, params, question)
    if not matches:
        return Answer(plain=f"I don't know anyone called {query or 'that'} yet.")
    if len(matches) > 1:
        options = "\n".join(f"  • {directory.name(e)} ({directory.meta[e].get('org', '')})" for e in matches)
        return Answer(plain=f"Which {query.title()}?\n{options}\nAsk again with their full name.")
    eid = matches[0]
    history = ctx.index.chunks_with_people(directory.identifiers(eid), before=ctx.now.isoformat())
    packet = Packet()
    for c in ctx.index.chunks_of(f"people/{eid}.md"):
        packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"])
    for c in history[:8]:
        packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
    meta = directory.meta[eid]
    about = f"The person asked about is {directory.name(eid)}."
    if meta.get("relationship"):
        about += f" They are your {meta['relationship']}."
    if meta.get("pronouns"):
        about += f" Pronouns: {meta['pronouns']}; use them."
    answer = synthesize(ctx, question, packet, INSTRUCTIONS.replace("{me_name}", ctx.me.name or "the user"),
                        extra_context=about)
    recent, seen = [], set()
    for h in history:
        if h["path"] not in seen:
            seen.add(h["path"])
            recent.append(h["label"])
        if len(recent) == 5:
            break
    answer.sections.insert(0, Section("At a glance", lines=person_lines(directory, eid, history,
                                                                       directory.facts(ctx.home, eid))))
    if recent:
        answer.sections.insert(1, Section("Recent", lines=recent))
    return answer
