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


def now_line(ctx: Ctx) -> str:
    """"Sun, Oct 4, 1:14 PM (2026-10-04T13:14-07:00)": the current local time, for the user message."""
    local = ctx.now.astimezone()
    return f"{local:%a, %b} {local.day}, {local:%-I:%M %p} ({local.isoformat(timespec='minutes')})"


def synthesize(ctx: Ctx, question: str, packet: Packet, instructions: str = "", tier: str = "strong",
               extra_context: str = "") -> Answer:
    # The system prompt holds nothing that changes per call (not even the time), so Gemini can
    # cache it. The question comes last, after the sources: models answer long inputs better so.
    system = load_prompt("answer", instructions=instructions)
    known = people_context(ctx, packet)
    user = (f"Now: {now_line(ctx)}\n\n{extra_context}\n\n{known}\n\nSources:\n\n{packet.render()}\n\n"
            f"Question (answer it from the sources above): {question}")
    while "\n\n\n" in user:
        user = user.replace("\n\n\n", "\n\n")
    out = ctx.backend.complete(system, user, SHAPE, tier=tier)
    summary = verify_claims(out.get("summary") or [], packet)
    answer = Answer(summary=summary.kept, packet=packet, unverified=list(summary.dropped))
    for sec in out.get("sections") or []:
        v = verify_claims(sec.get("items") or [], packet)
        answer.unverified += v.dropped
        if v.kept:
            answer.sections.append(Section(sec.get("heading", ""), v.kept))
    answer.dropped = len(answer.unverified)
    return answer
