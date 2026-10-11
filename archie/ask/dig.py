"""Dig further when an answer doesn't help (spec: dig-deeper §2).

The model has no tools; Archie is the tool. Each round, one fast-tier call reads the
question, what the first answer missed, and a notebook of what's been tried, and picks one
step from a fixed read-only menu (search, open a file, look someone up, list the calendar),
all over the user's own files. Code runs it and writes the result into the notebook. Every excerpt a step
returns joins one packet, and the answer is written from that packet by `synthesize`, so the
verifier checks it like any other. Rounds and money are capped per question."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Shape
from archie.llm.verify import Packet, tidy

STEPS = ("search", "open", "person", "calendar", "answer")
SHAPE = Shape("dig_step", fields=(
    F("why", required=False, hint="one line: what you expect to learn"),
    F("do", "choice", choices=STEPS, lenient=True),
    F("arg", required=False, hint="the query, path, name or dates; - for answer"),
    F("new_person", required=False, hint="answer only: full name of someone asked about with no people file")),
    example="why: the calendar titles mention Workpersontwo Birch\ndo: search\narg: Workpersontwo Birch")

OPENABLE = ("people/", "meetings/", "loops/", "projects/", "journal/")  # Archie's notes; sources only once shown
HITS_SHOWN = 8
EXCERPT_CHARS = 300
OPEN_CHARS = 12_000
MAX_MEETINGS = 30
MAX_RANGE_DAYS = 92
FAST_CALL_USD = 0.01  # high estimates of one call, checked against ask.dig.max_usd before each round
STRONG_CALL_USD = 0.06
DIG_INSTRUCTIONS = """- Archie's first answer fell short; "What the first answer missed" says what the user wanted. Answer that."""
NOUNS = {"search": ("search", "searches"), "open": ("file read", "files read"),
         "person": ("people lookup", "people lookups"), "calendar": ("calendar check", "calendar checks")}

Progress = Callable[[str], None]


@dataclass
class DigResult:
    answer: Answer | None  # None: nothing verified came of it
    actions: list[str] = field(default_factory=list)  # "search: Workpersontwo Birch", as run
    new_person: str | None = None  # the model's suggestion; offer.py checks it
    usd: float = 0.0
    packet: Packet = field(default_factory=Packet)

    def log(self) -> dict:
        return {"rounds": len(self.actions), "actions": self.actions, "improved": self.answer is not None,
                "usd": round(self.usd, 4)}

    def work(self) -> str:
        """"3 searches, 1 calendar check": the steps that ran, by kind, in order."""
        counts = Counter(a.split(":", 1)[0] for a in self.actions if not a.startswith("refused"))
        return ", ".join(f"{n} {NOUNS[k][n != 1]}" for k, n in counts.items() if k in NOUNS)

    def nothing_more(self) -> str | None:
        """None when no step ran (every one refused, or the model call failed): nothing to claim."""
        work = self.work()
        return f"I looked further ({work}) and found nothing more." if work else None


class _Dig:
    def __init__(self, ctx: Ctx, start: Packet | None, progress: Progress | None):
        from archie.ask.intents.search import limits

        self.ctx, self.progress = ctx, progress or (lambda _: None)
        self.max_items, self.max_chars = limits(ctx)
        self.packet = Packet()
        self.used = 0
        for it in (start.items if start else []):
            self._add(it.path, it.chunk_id, it.text, it.label, it.ts)
        self.shown = {it.path for it in self.packet.items}  # paths the model may open
        self.notebook: list[str] = []
        self.actions: list[str] = []
        self.tried: set[tuple[str, str]] = set()
        if self.packet.items:
            self.notebook.append("Sources the first answer used:\n" + self._listing(self.packet.items[:HITS_SHOWN]))

    def _add(self, path: str, chunk_id: str, text: str, label: str = "", ts: str | None = None) -> int | None:
        for it in self.packet.items:
            if it.path == path and it.chunk_id == chunk_id:
                return it.ref
        if len(self.packet.items) >= self.max_items or self.used + len(text) > self.max_chars:
            return None
        self.used += len(text)
        return self.packet.add(path, chunk_id, text, label=label, ts=ts)

    def _listing(self, items) -> str:
        lines = []
        for it in items:
            excerpt = " ".join(tidy(it.text).split())[:EXCERPT_CHARS]
            lines.append(f"[{it.ref}] {it.label} ({it.path}): {excerpt}")
        return "\n".join(lines)

    def _added(self, chunks: list[dict]) -> str:
        """Add chunks to the packet; their listing for the notebook."""
        items = []
        chunks = [c for c in chunks if tidy(c["text"])]  # a data block alone says nothing
        for c in chunks:
            ref = self._add(c["path"], c["chunk_id"], c["text"], c.get("label") or c["path"], c.get("ts"))
            if ref is not None:
                items.append(self.packet.get(ref))
                self.shown.add(c["path"])
        full = "" if len(items) == len(chunks) else "\n(Some results didn't fit: the notes are full.)"
        return (self._listing(items) or "(nothing new)") + full

    # -- steps ------------------------------------------------------------------------
    def run(self, n: int, step: dict) -> None:
        do, arg = step.get("do"), " ".join(str(step.get("arg") or "").split())
        head = f"Step {n}: {do or '?'}: {arg}" + (f"\nWhy: {step['why']}" if step.get("why") else "")
        refusal = self._refusal(do, arg)
        if refusal:
            self.actions.append(f"refused: {do or '?'}: {arg}")
            self.notebook.append(f"{head}\n(refused: {refusal})")
            return
        self.tried.add((do, arg.lower()))
        result = getattr(self, f"_{do}")(arg)
        self.actions.append(f"{do}: {arg}")
        self.notebook.append(f"{head}\nResult:\n{result}")

    def _refusal(self, do: str | None, arg: str) -> str | None:
        if do not in STEPS or do == "answer":
            return "not a step on the list"
        if not arg:
            return f"{do} needs an argument"
        if (do, arg.lower()) in self.tried:
            return "already done"
        if do == "open" and not self._openable(arg):
            return "only paths shown in results, or Archie's notes, can be opened"
        return None

    def _openable(self, path: str) -> bool:
        parts = path.split("/")
        if path.startswith("/") or ".." in parts:
            return False
        return path in self.shown or path.startswith(OPENABLE)

    def _search(self, arg: str) -> str:
        from archie.ask.actions import EMPTY
        from archie.ask.intents.search import find

        self.progress(f"Looking further… searching “{arg}”")
        hits = find(self.ctx, arg, dict(EMPTY))[:HITS_SHOWN]
        return self._added([{"path": h.path, "chunk_id": h.chunk_id, "text": h.text, "label": h.label, "ts": h.ts}
                            for h in hits]) if hits else "(nothing found)"

    def _open(self, path: str) -> str:
        self.progress(f"Looking further… reading {path}")
        chunks, used = [], 0
        for c in self.ctx.index.chunks_of(path):
            if used + len(c["text"]) > OPEN_CHARS:
                break
            chunks.append(c)
            used += len(c["text"])
        return self._added(chunks) if chunks else "(nothing indexed at that path)"

    def _person(self, name: str) -> str:
        from archie.derive.people import PeopleDirectory, org

        self.progress(f"Looking further… looking up {name}")
        d = PeopleDirectory.load(self.ctx.home)
        hits = d.find(name) or d.find(name, loose=True) or d.near(name)
        if not hits:
            return f"(no people file on anyone called {name})"
        lines = []
        for eid in hits[:5]:
            meta = d.meta[eid]
            aliases = ", ".join(str(a) for a in meta.get("aliases") or [])
            bits = [d.label(eid), f"aliases: {aliases}" if aliases else "", f"org: {org(meta)}" if org(meta) else "",
                    f"people/{eid}.md"]
            lines.append(" · ".join(b for b in bits if b))
            self._added(self.ctx.index.chunks_of(f"people/{eid}.md")[:3])
        return "\n".join(lines)

    def _calendar(self, arg: str) -> str:
        from archie.derive.meetings import load_meetings

        days = re.findall(r"\d{4}-\d\d-\d\d", arg)
        try:
            first = date.fromisoformat(days[0])
            last = date.fromisoformat(days[1]) if len(days) > 1 else first
        except (IndexError, ValueError):
            return "(give two dates: YYYY-MM-DD YYYY-MM-DD)"
        last = min(last, first + timedelta(days=MAX_RANGE_DAYS))
        self.progress(f"Looking further… checking your calendar {first:%b} {first.day} to {last:%b} {last.day}")
        found = []
        for m in load_meetings(self.ctx.home):
            try:
                start = datetime.fromisoformat(m.meta["start"]).astimezone()
            except (KeyError, TypeError, ValueError):
                continue
            if first <= start.date() <= last:
                found.append((start, m))
        found.sort(key=lambda x: x[0])
        lines = []
        for start, m in found[:MAX_MEETINGS]:
            names = ", ".join(str(n) for n in m.meta.get("attendee_names") or []) or "no one else"
            flags = [w for w, on in (("cancelled", m.meta.get("status") == "cancelled"),
                                     ("personal", m.meta.get("type") == "event")) if on]
            line = f"{start:%a %b} {start.day}, {start:%-I:%M %p} · {m.meta.get('title')} · with {names}"
            lines.append(line + (f" ({', '.join(flags)})" if flags else "") + f" · {m.rel_path}")
            self._added([c for c in self.ctx.index.chunks_of(m.rel_path) if tidy(c["text"])][:1])
        more = f"\n(and {len(found) - MAX_MEETINGS} more)" if len(found) > MAX_MEETINGS else ""
        return ("\n".join(lines) + more) if lines else "(nothing on the calendar then)"

    # -- prompts ------------------------------------------------------------------------
    def system(self) -> str:
        return load_prompt("dig_step", me_name=self.ctx.me.name or "the user")

    def prompt(self, question: str, hint: str) -> str:
        from archie.ask.synthesize import now_line, people_context

        notebook = "\n\n".join(self.notebook) or "(empty: nothing tried yet)"
        return "\n\n".join(filter(None, [
            f"Now: {now_line(self.ctx)}", people_context(self.ctx, self.packet),
            f"Question: {question}", f"What the first answer missed: {hint}", f"Notebook:\n\n{notebook}",
            "Choose the next step."]))


def dig(ctx: Ctx, question: str, hint: str, start: Packet | None = None,
        progress: Progress | None = None) -> DigResult:
    from archie.ask.synthesize import synthesize

    cfg = ctx.config["ask"]["dig"]
    rounds, max_usd = int(cfg.get("rounds", 5)), float(cfg.get("max_usd", 0.25))
    budget = getattr(ctx.backend, "budget", None)
    spent_before = budget.session_usd if budget else 0.0

    def spent() -> float:
        return (budget.session_usd - spent_before) if budget else 0.0

    d = _Dig(ctx, start, progress)
    system = d.system()
    new_person = None
    for n in range(1, rounds + 1):
        if spent() + FAST_CALL_USD + STRONG_CALL_USD > max_usd:
            break
        try:
            d.progress(f"Looking further… deciding what to check next (round {n} of {rounds})")
            step = ctx.backend.complete(system, d.prompt(question, hint), SHAPE, tier="fast")
        except LLMError:
            break
        if step.get("do") == "answer":
            new_person = (step.get("new_person") or "").strip() or None
            break
        d.run(n, step)
    result = DigResult(None, d.actions, new_person, packet=d.packet)
    if d.packet.items:
        d.progress("Looking further… writing the answer")
        try:
            answer = synthesize(ctx, question, d.packet, DIG_INSTRUCTIONS, extra_context=f"What the first answer "
                                                                                         f"missed: {hint}")
        except LLMError:
            answer = None
        if answer is not None and (answer.summary or answer.sections):
            work = result.work()
            if work:
                answer.notes.append(f"I looked further: {work}.")
            result.answer = answer
    result.usd = spent()
    return result
