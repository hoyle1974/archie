"""`catchup`: what happened while the user was away (Vignette I).

Code computes what opened for the user in the window (loops) and which meetings happened;
the LLM summarizes changes and decisions from what involved the user's people and
projects (no newsletters or automated mail)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from archie.ask.answer import Answer, Section
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.ask.intents.loops import _claim, _line
from archie.ask.synthesize import synthesize
from archie.derive.loops import load_loops, rank
from archie.derive.meetings import load_meetings
from archie.index.chunk import short_date
from archie.llm.verify import Packet
from archie.store.files import read_raw

INSTRUCTIONS = """- {me_name} was away. Summary: the 2-3 most important things that happened.
- Sections: "Decisions" (made without them), "What changed" (in their projects).
- Skip routine notifications."""
WORK_SOURCES = ("gmail", "github", "jira", "drive", "meetings")


def _window(ctx: Ctx, params: dict) -> tuple[datetime, datetime]:
    tz = ctx.now.astimezone().tzinfo

    def parse(s):
        try:
            return date.fromisoformat((s or "")[:10])
        except ValueError:
            return None

    start = parse(params.get("since")) or (ctx.now.astimezone().date() - timedelta(days=7))
    end = parse(params.get("until"))
    return datetime.combine(start, time.min, tz), datetime.combine(end, time.max, tz) if end else ctx.now


def _human_mail(path: str, chunk_id: str, cache: dict) -> bool:
    """Gmail chunks only from personal (non-bulk) messages."""
    if path not in cache:
        cache[path] = read_raw(path)
    msgs = cache[path].get("messages") or []
    i = int(chunk_id[1:]) if chunk_id[1:].isdigit() else 0
    return i < len(msgs) and not msgs[i].get("bulk") and "CATEGORY_UPDATES" not in (msgs[i].get("labels") or [])


@intent("catchup")
def catchup_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    start, end = _window(ctx, params)
    s_iso, e_iso = start.isoformat(), end.isoformat()
    rows = ctx.index.query(
        "SELECT path, chunk_id, text, source, ts, label FROM chunks WHERE ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 400",
        (s_iso, e_iso))
    packet, cache = Packet(), {}
    for path, chunk, text, source, ts, label in rows:
        if source not in WORK_SOURCES:
            continue
        if source == "gmail" and not _human_mail(str(ctx.home / path), chunk, cache):
            continue
        packet.add(path, chunk, text, label=label, ts=ts)
        if len(packet.items) >= 30:
            break
    opened = [r for r in rank(load_loops(ctx.home), ctx.now, ctx.config)
              if s_iso <= r.loop.meta["created_at"] <= e_iso]
    met = [m for m in load_meetings(ctx.home) if s_iso <= m.meta["start"] <= min(e_iso, ctx.now.isoformat())
           and m.meta.get("status") == "scheduled"]
    if not packet.items and not opened and not met:
        return Answer(plain=f"Nothing involving you since {short_date(s_iso)}.")
    answer = synthesize(ctx, question, packet, INSTRUCTIONS.replace("{me_name}", ctx.me.name or "the user"),
                        extra_context=f"Away from {short_date(s_iso)} to {short_date(e_iso)}.") if packet.items \
        else Answer()
    if opened:
        answer.sections.insert(0, Section("Opened while you were out",
                                          items=[_claim(ctx, r, _line(r)) for r in opened[:10]]))
    if met:
        lines = [f"{m.meta.get('title')} ({short_date(m.meta['start'])})"
                 + (" · has notes" if "## My notes\n\n" not in (ctx.home / m.rel_path).read_text() else "")
                 for m in sorted(met, key=lambda m: m.meta["start"])]
        answer.sections.append(Section("Meetings in that window", lines=lines))
    return answer
