"""Turn a context packet into a verified Answer (DESIGN §8 steps 3–4)."""

from __future__ import annotations

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.shape import Shape
from archie.llm.verify import Packet, verify_claims

SHAPE = Shape("answer", claims=True)


def describe(meta: dict, name: str) -> str | None:
    bits = [f"your {meta['relationship']}" if meta.get("relationship") else None, meta.get("identity"),
            f"pronouns {meta['pronouns']}" if meta.get("pronouns") else None, meta.get("role")]
    if meta.get("avoid"):
        bits.append("never call them: " + ", ".join(meta["avoid"]))
    bits = [b for b in bits if b]
    return f"{name}: {'; '.join(bits)}" if bits else None


def packet_text(packet: Packet) -> str:
    return "\n".join(it.text + " " + it.label for it in packet.items)


def people_context(ctx: Ctx, packet: Packet) -> str:
    """What the user has told Archie about anyone the sources mention. It overrides how the
    sources describe them (an email saying "my son" about the user's non-binary child)."""
    from archie.derive.people import PeopleDirectory

    d = PeopleDirectory.load(ctx.home)
    lines = [f"- {line}" for eid in d.mentioned_in(packet_text(packet)) if (line := describe(d.meta[eid], d.name(eid)))]
    if not lines:
        return ""
    return ("What you've told me about people mentioned below. These override how the sources describe "
            "them: use these relationship words and pronouns, never a gendered word the user hasn't used:\n"
            + "\n".join(lines[:15]))


def synthesize(ctx: Ctx, question: str, packet: Packet, instructions: str = "", tier: str = "strong",
               extra_context: str = "") -> Answer:
    system = load_prompt("answer", me_name=ctx.me.name or "the user",
                         now=ctx.now.astimezone().isoformat(timespec="minutes"), instructions=instructions)
    known = people_context(ctx, packet)
    user = f"Question: {question}\n\n{extra_context}\n\n{known}\n\nSources:\n\n{packet.render()}"
    while "\n\n\n" in user:
        user = user.replace("\n\n\n", "\n\n")
    out = ctx.backend.complete(system, user, SHAPE, tier=tier)
    summary = verify_claims(out.get("summary") or [], packet)
    answer = Answer(summary=summary.kept, packet=packet, dropped=len(summary.dropped))
    for sec in out.get("sections") or []:
        v = verify_claims(sec.get("items") or [], packet)
        answer.dropped += len(v.dropped)
        if v.kept:
            answer.sections.append(Section(sec.get("heading", ""), v.kept))
    return answer
