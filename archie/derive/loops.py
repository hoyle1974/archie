"""Open loops (DESIGN §6): detect in new mail, close on evidence, rank by code.

Rules enforced in code, not trusted to the model:
- every loop cites a verbatim quote from the message it came from;
- kind matches direction: asked_of_me cites someone else's message; i_promised and
  waiting_on cite the user's own message;
- the counterpart comes from the message headers, not the model;
- closing needs a verified quote from a NEW message (or the user's word);
- a status the user set (done, dismissed, snoozed) is never overwritten.
Messages are processed once: state/loops_seen.yaml remembers each thread's last message.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from archie.ask.context import Ctx
from archie.connectors.gmail import chunk_thread
from archie.derive.people import PeopleDirectory, looks_personal, slug
from archie.llm.backend import LLMError
from archie.llm.prompts import load_prompt
from archie.llm.verify import Packet, check_quote, normalize
from archie.store.fence import get_fence, set_fence
from archie.store.files import Note, atomic_write, read_note, read_raw, write_note
from archie.store.home import Home

KINDS = ("asked_of_me", "i_promised", "waiting_on")
OPEN = ("open", "maybe_done")
USER_STATUSES = ("done", "dismissed", "snoozed")

EXTRACT_SCHEMA = {
    "title": "loops_extract",
    "type": "object",
    "properties": {"loops": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)}, "summary": {"type": "string"},
            "ref": {"type": "integer"}, "quote": {"type": "string"}, "due": {"type": ["string", "null"]},
            "resolved": {"type": "boolean"}, "resolved_ref": {"type": ["integer", "null"]},
            "resolved_quote": {"type": ["string", "null"]}},
        "required": ["kind", "summary", "ref", "quote", "due", "resolved", "resolved_ref", "resolved_quote"],
        "additionalProperties": False}}},
    "required": ["loops"],
    "additionalProperties": False,
}

CLOSE_SCHEMA = {
    "title": "loops_close",
    "type": "object",
    "properties": {"updates": {"type": "array", "items": {
        "type": "object",
        "properties": {"loop": {"type": "integer"}, "resolved": {"type": "boolean"}, "ref": {"type": "integer"},
                       "quote": {"type": "string"}},
        "required": ["loop", "resolved", "ref", "quote"], "additionalProperties": False}}},
    "required": ["updates"],
    "additionalProperties": False,
}


@dataclass
class Loop:
    loop_id: str
    rel_path: str
    note: Note

    @property
    def meta(self) -> dict:
        return self.note.meta


def load_loops(home: Home) -> list[Loop]:
    out = []
    for p in sorted((home / "loops").rglob("*.md")):
        note = read_note(p)
        out.append(Loop(note.meta.get("loop_id", p.stem), p.relative_to(home.root).as_posix(), note))
    return out


def save_loop(home: Home, loop: Loop) -> None:
    write_note(home / loop.rel_path, loop.note)


def _history(loop: Loop, line: str) -> None:
    current = get_fence(loop.note.body) or "## History\n"
    loop.note.body = set_fence(loop.note.body, current + f"- {line}\n")


def _seen_file(home: Home) -> Path:
    return home / "state/loops_seen.yaml"


def _relevant(m: dict) -> bool:
    if m.get("bulk"):
        return False
    return bool(m.get("from_me")) or ((m.get("to_me") or m.get("cc_me")) and looks_personal(m))


def _counterpart(m: dict, me, directory: PeopleDirectory) -> tuple[str, str]:
    if m.get("from_me"):
        others = [a for a in m.get("to", []) + m.get("cc", []) if not me.is_me(a["email"])]
        if not others:
            return "", ""
        email, name = others[0]["email"], others[0].get("name") or others[0]["email"]
    else:
        email, name = m.get("from_email", ""), m.get("from_name") or m.get("from_email", "")
    eid = directory.by_email(email)
    return (eid, directory.name(eid)) if eid else (email, name)


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone()


def _packet(rel: str, data: dict, new: set[int]) -> Packet:
    p = Packet()
    for i, c in enumerate(chunk_thread(rel, data)):
        tag = " NEW" if i in new else ""
        p.add(c.path, c.chunk_id, c.text, label=f"{c.label}{tag}")
    return p


def _valid_due(due: str | None) -> str | None:
    try:
        return date.fromisoformat(due).isoformat() if due else None
    except ValueError:
        return None


def _close(ctx: Ctx, packet: Packet, open_here: list[Loop], new_refs: set[int], tid: str) -> None:
    listing = "\n".join(f"{n}. ({lp.meta['kind']}) {lp.meta['summary']}" for n, lp in enumerate(open_here, 1))
    system = load_prompt("loops_close", me_name=ctx.me.name or "the user")
    user = f"Open loops:\n{listing}\n\nThread (NEW messages are marked):\n\n{packet.render()}"
    out = ctx.backend.complete(system, user, CLOSE_SCHEMA, tier="fast")
    for upd in out.get("updates") or []:
        n = int(upd.get("loop", 0))
        if not upd.get("resolved") or not 1 <= n <= len(open_here) or int(upd.get("ref", 0)) not in new_refs:
            continue
        cite = check_quote(packet, int(upd["ref"]), upd.get("quote", ""))
        loop = open_here[n - 1]
        if cite is None or loop.meta.get("status") in USER_STATUSES:
            continue
        loop.meta["status"] = "done"
        loop.meta["closed_by"] = {"file": cite.path, "chunk": cite.chunk_id, "quote": cite.quote}
        _history(loop, f"{ctx.now.date().isoformat()} closed by a later message in the thread")
        save_loop(ctx.home, loop)


def _extract(ctx: Ctx, packet: Packet, data: dict, rel: str, tid: str, new_refs: set[int],
             directory: PeopleDirectory, known: set[str]) -> None:
    system = load_prompt("loops_extract", me_name=ctx.me.name or "the user",
                         today=ctx.now.astimezone().date().isoformat())
    out = ctx.backend.complete(system, f"Thread:\n\n{packet.render()}", EXTRACT_SCHEMA, tier="fast")
    msgs = data["messages"]
    for c in out.get("loops") or []:
        ref, kind = int(c.get("ref", 0)), c.get("kind")
        if ref not in new_refs or kind not in KINDS:
            continue
        cite = check_quote(packet, ref, c.get("quote", ""))
        if cite is None:
            continue
        m = msgs[ref - 1]
        if (kind == "asked_of_me") == bool(m.get("from_me")):
            continue  # direction doesn't match the kind
        if c.get("resolved") and c.get("resolved_ref") and check_quote(packet, int(c["resolved_ref"]),
                                                                        c.get("resolved_quote") or ""):
            continue  # already settled later in the thread
        cp_id, cp_name = _counterpart(m, ctx.me, directory)
        if not cp_id:
            continue
        h = hashlib.sha1(f"{tid}|{m['id']}|{kind}|{normalize(cite.quote)}".encode()).hexdigest()[:6]
        when = _local(m["date"])
        loop_id = f"loop-{when:%Y%m%d-%H%M}-{slug(cp_name)[:24]}-{h}"
        if loop_id in known:
            continue
        known.add(loop_id)
        meta = {"loop_id": loop_id, "kind": kind, "status": "open", "counterpart": cp_id,
                "counterpart_name": cp_name, "summary": c.get("summary", "").strip(), "created_at": m["date"],
                "due": _valid_due(c.get("due")), "snoozed_until": None, "thread": tid,
                "addressed": "to" if m.get("to_me") or m.get("from_me") else "cc",
                "sources": [{"file": cite.path, "chunk": cite.chunk_id, "quote": cite.quote}], "closed_by": None}
        loop = Loop(loop_id, f"loops/{when:%Y}/{loop_id}.md", Note(meta=meta, body=""))
        _history(loop, f"{when:%Y-%m-%d %H:%M} opened from email")
        save_loop(ctx.home, loop)


def derive_loops(ctx: Ctx, paths: list[Path]) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    seen = (yaml.safe_load(_seen_file(ctx.home).read_text()) or {}) if _seen_file(ctx.home).exists() else {}
    directory = PeopleDirectory.load(ctx.home)
    loops = load_loops(ctx.home)
    known = {lp.loop_id for lp in loops}
    by_thread: dict[str, list[Loop]] = {}
    for lp in loops:
        by_thread.setdefault(str(lp.meta.get("thread")), []).append(lp)
    lock = threading.Lock()

    class _Known:  # set-like view guarded by a lock, shared by worker threads
        def __contains__(self, item):
            with lock:
                return item in known

        def add(self, item):
            with lock:
                known.add(item)

    def process(path: Path) -> tuple[str, str] | None:
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/gmail/") or not Path(path).exists():
            return None
        data = read_raw(path)
        msgs = data.get("messages") or []
        tid = str(data.get("id") or Path(path).stem)
        if data.get("deleted") or not msgs:
            return None
        new = {i for i, m in enumerate(msgs) if m["date"] > seen.get(tid, "")}
        if not new:
            return None
        relevant_new = {i + 1 for i in new if _relevant(msgs[i])}
        if relevant_new:
            packet = _packet(rel, data, new)
            open_here = [lp for lp in by_thread.get(tid, []) if lp.meta.get("status") in OPEN]
            try:
                if open_here:
                    _close(ctx, packet, open_here, relevant_new, tid)
                _extract(ctx, packet, data, rel, tid, relevant_new, directory, _Known())
            except LLMError:
                return None  # leave the thread unseen; the next cycle retries it
        return tid, max(m["date"] for m in msgs)

    workers = max(1, int(ctx.config["llm"].get("parallel", 1)))
    finished = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(process, sorted(paths)):
            if not result:
                continue
            seen[result[0]] = result[1]
            finished += 1
            if finished % 10 == 0:  # save progress during long backfills
                atomic_write(_seen_file(ctx.home), yaml.safe_dump(seen, sort_keys=True))
    if finished:
        atomic_write(_seen_file(ctx.home), yaml.safe_dump(seen, sort_keys=True))


@dataclass
class Ranked:
    loop: Loop
    score: float
    why: list[str] = field(default_factory=list)


def _days(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 86400


def is_active(loop: Loop, now: datetime) -> bool:
    st = loop.meta.get("status")
    if st == "snoozed":
        until = loop.meta.get("snoozed_until")
        return bool(until) and until <= now.astimezone().date().isoformat()
    return st in OPEN


def rank(loops: list[Loop], now: datetime, config: dict, upcoming_people: set[str] | None = None) -> list[Ranked]:
    """Explainable ranking (DESIGN §6.5): each score comes with the reasons behind it."""
    w = config["loops"]["weights"]
    today = now.astimezone().date()
    out = []
    for lp in loops:
        if not is_active(lp, now):
            continue
        m, score, why = lp.meta, 0.0, []
        score += w.get(m.get("kind"), 0.0)
        if m.get("due"):
            days_left = (date.fromisoformat(m["due"]) - today).days
            if days_left < 0:
                score += w["overdue"]
                why.append(f"overdue since {m['due']}")
            elif days_left <= 2:
                score += w["due_soon"]
                why.append("due today" if days_left == 0 else f"due in {days_left} day{'s' if days_left > 1 else ''}")
        age = max(0.0, _days(now, datetime.fromisoformat(m["created_at"])))
        score += min(age, 10) * w["age_per_day"]
        if age >= 2:
            why.append(f"{int(age)} days old")
        if m.get("addressed") == "to":
            score += w["to_not_cc"]
        if upcoming_people and m.get("counterpart") in upcoming_people:
            score += w["in_upcoming_meeting"]
            why.append("you're meeting them soon")
        out.append(Ranked(lp, score, why))
    return sorted(out, key=lambda r: -r.score)
