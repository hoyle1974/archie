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
from archie.derive.people import PeopleDirectory, org
from archie.index.chunk import short_date
from archie.llm.verify import Claim, Packet
from archie.store.times import when

INSTRUCTIONS = """- Start with who this person is (role, how {me_name} knows them) if the sources say.
- Then the most recent thing they discussed or anything still open between them.
- Keep the summary to 2-3 sentences."""


_ASKED = re.compile(r"(?:who is|who's|history with)\s+([\w@.\-'’ ]+)", re.I)


def resolve(ctx: Ctx, params: dict, question: str) -> tuple[PeopleDirectory, list[str], str]:
    """(directory, matching ids, the name the user used). A topic is never used as a name."""
    directory = PeopleDirectory.load(ctx.home)
    names = list(params.get("people") or [])
    m = _ASKED.search(question)
    if not names and m:
        names = [m.group(1).strip(" ?")]
    for name in names:
        hits = directory.find(name)
        if hits:
            return directory, hits, name
    found = directory.names_in(question)
    if found:
        return directory, found, directory.name(found[0]).split(" ")[0]
    return directory, [], names[0] if names else ""


def unknown_person(ctx: Ctx, question: str, params: dict, name: str) -> Answer:
    """No known person: search the whole question instead of giving up (spec §4c)."""
    from archie.ask.intents.search import search_intent

    lead = f"I didn't recognise anyone called {name}" if name else "I couldn't tell who you meant"
    answer = search_intent(ctx, question, {**params, "people": []})
    if answer.nothing_found or not (answer.summary or answer.sections):
        return Answer(plain=f"{lead}, and a search found nothing about it.")
    answer.summary.insert(0, Claim(f"{lead}, so I searched everything instead.", []))
    return answer


def person_lines(directory: PeopleDirectory, eid: str, history: list[dict], facts: list[dict] | None = None) -> list[str]:
    meta = directory.meta[eid]
    lines = [directory.label(eid)]
    personal = [b for b in (f"Your {meta['relationship']}" if meta.get("relationship") else None,
                            meta.get("identity"), meta.get("pronouns")) if b]
    if personal:
        lines.append(" · ".join(personal))
    if facts and not meta.get("role"):
        lines.append("Known for: " + "; ".join(f["text"] for f in facts[:3]))
    if meta.get("role"):
        lines.append(f"Role: {meta['role']}")
    if org(meta):
        lines.append(f"Org: {org(meta)}")
    if meta.get("last_interaction"):
        lines.append(f"Last talked: {when(meta['last_interaction'])}"
                     f" · first seen {short_date(meta.get('first_seen'))}")
    threads = {h["path"] for h in history if h["source"] == "gmail"}
    if threads:
        lines.append(f"{len(threads)} email thread{'s' if len(threads) != 1 else ''} together")
    return lines


def told_sentence(directory: PeopleDirectory, eid: str) -> str | None:
    """One plain sentence from what the user told Archie: "Sam is your neighbor." """
    meta = directory.meta[eid]
    name = directory.name(eid)
    if meta.get("relationship"):
        return f"{name} is your {meta['relationship']}."
    if meta.get("role"):
        return f"{name}: {meta['role']}."
    return None


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
        extra = "".join(f" · {m[k]}" for k in ("identity", "pronouns") if m.get(k))
        lines.append(f"  • {d.label(e)}: your {m['relationship']}{extra}")
    return Answer(plain="Your family, as you've told me:\n" + "\n".join(lines))


@intent("who")
def who_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    if re.search(r"\bmy (family|kids|children|parents)\b", question, re.I) or \
            re.search(r"\bfamily\b", str(params.get("topic") or ""), re.I):
        return family_answer(ctx)
    directory, matches, query = resolve(ctx, params, question)
    if not matches:
        return unknown_person(ctx, question, params, query)
    if len(matches) > 1:
        options = "\n".join(f"  • {directory.name(e)}" + (f" ({org(directory.meta[e])})" if org(directory.meta[e]) else "")
                            for e in matches)
        return Answer(plain=f"Which {query.title()}?\n{options}\nAsk again with their full name.")
    eid = matches[0]
    history = ctx.index.chunks_with_people(directory.identifiers(eid), before=ctx.now.isoformat())
    packet = Packet()
    for c in ctx.index.chunks_of(f"people/{eid}.md"):
        packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"])
    from archie.ask.intents.search import limits

    k, room = limits(ctx)
    room -= sum(len(it.text) for it in packet.items)
    for c in history:  # newest first, as many as fit
        if len(packet.items) >= k:
            break
        if len(c["text"]) <= room:
            packet.add(c["path"], c["chunk_id"], c["text"], label=c["label"], ts=c["ts"])
            room -= len(c["text"])
    meta = directory.meta[eid]
    about = f"The person asked about is {directory.name(eid)}."
    if meta.get("full_name"):
        about += f" Full name: {meta['full_name']}."
    if meta.get("relationship"):
        about += f" They are your {meta['relationship']}."
    if meta.get("identity"):
        about += f" They are {meta['identity']}."
    if meta.get("pronouns"):
        about += f" Pronouns: {meta['pronouns']}; use them."
    if meta.get("avoid"):
        about += f" Never call them: {', '.join(meta['avoid'])}."
    answer = synthesize(ctx, question, packet, INSTRUCTIONS.replace("{me_name}", ctx.me.name or "the user"),
                        extra_context=about)
    told = told_sentence(directory, eid)
    said = " ".join(c.text for c in answer.summary).lower()
    if not answer.summary:  # the model had nothing to cite: open with what you told me
        only = " That's all I know so far." if not history else ""
        answer.summary = [Claim((told or f"I have {directory.name(eid)} on file, but nothing that says who they are.")
                                + only, [])]
    elif told and meta.get("relationship") and str(meta["relationship"]).lower() not in said:
        answer.summary.insert(0, Claim(told, []))  # what you said leads, even if the mail never says it
    recent, seen = [], set()
    for h in history:  # one meeting on several calendars is several files with one label
        if h["path"] not in seen and h["label"] not in recent:
            seen.add(h["path"])
            recent.append(h["label"])
        if len(recent) == 5:
            break
    answer.sections.insert(0, Section("At a glance", lines=person_lines(directory, eid, history,
                                                                       directory.facts(ctx.home, eid))))
    if recent:
        answer.sections.insert(1, Section("Recent", lines=recent))
    return answer
