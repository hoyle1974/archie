"""Turn a context packet into a verified Answer (DESIGN §8 steps 3–4)."""

from __future__ import annotations

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, verify_claims

_CLAIM = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "citations": {"type": "array", "items": {
            "type": "object", "properties": {"ref": {"type": "integer"}, "quote": {"type": "string"}},
            "required": ["ref", "quote"], "additionalProperties": False}},
    },
    "required": ["text", "citations"],
    "additionalProperties": False,
}

SCHEMA = {
    "title": "answer",
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": _CLAIM},
        "sections": {"type": "array", "items": {
            "type": "object", "properties": {"heading": {"type": "string"}, "items": {"type": "array", "items": _CLAIM}},
            "required": ["heading", "items"], "additionalProperties": False}},
    },
    "required": ["summary", "sections"],
    "additionalProperties": False,
}


def synthesize(ctx: Ctx, question: str, packet: Packet, instructions: str = "", tier: str = "strong",
               extra_context: str = "") -> Answer:
    system = load_prompt("answer", me_name=ctx.me.name or "the user",
                         now=ctx.now.astimezone().isoformat(timespec="minutes"), instructions=instructions)
    user = f"Question: {question}\n\n{extra_context}\n\nSources:\n\n{packet.render()}".replace("\n\n\n", "\n\n")
    out = ctx.backend.complete(system, user, SCHEMA, tier=tier)
    summary = verify_claims(out.get("summary") or [], packet)
    answer = Answer(summary=summary.kept, packet=packet, dropped=len(summary.dropped))
    for sec in out.get("sections") or []:
        v = verify_claims(sec.get("items") or [], packet)
        answer.dropped += len(v.dropped)
        if v.kept:
            answer.sections.append(Section(sec.get("heading", ""), v.kept))
    return answer
