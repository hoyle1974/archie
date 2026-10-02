"""What the user did in a time window, computed from raw files (no LLM). Each item points
at the exact chunk it came from, so it can be shown with a citation. Feeds the standup,
the ledger, the weekly journal and catch-up (Vignettes A-standup, E, I, K)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from archie.ask.context import Ctx
from archie.store.files import read_raw

KIND_WORDS = {"commit": "Commits", "pr_merged": "PRs merged", "pr_opened": "PRs opened", "review_given": "Reviews",
              "issue_done": "Issues closed", "transition": "Issues moved", "doc_edited": "Docs edited",
              "email_sent": "Emails sent", "meeting": "Meetings"}


@dataclass
class Item:
    when: str
    kind: str
    title: str
    project: str
    path: str
    chunk: str
    quote: str


def _in(ts: str | None, start: datetime, end: datetime) -> bool:
    if not ts:
        return False
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return start <= t < end


def _rel(ctx: Ctx, p) -> str:
    return p.relative_to(ctx.home.root).as_posix()


def my_activity(ctx: Ctx, start: datetime, end: datetime) -> list[Item]:
    out: list[Item] = []
    me = ctx.me
    for p in sorted((ctx.home / "sources/github").rglob("*.json")):
        d = read_raw(p)
        if d.get("deleted"):
            continue
        rel = _rel(ctx, p)
        if "sha" in d:
            if d.get("author") == (me.github or d.get("author")) and _in(d["date"], start, end):
                first = d["message"].splitlines()[0]
                out.append(Item(d["date"], "commit", first, d["repo"], rel, "c0", first))
            continue
        mine = d.get("author") == d.get("me")
        kind = "PR" if d.get("kind") == "pr" else "Issue"
        if mine and d.get("merged") and _in(d.get("merged_at"), start, end):
            out.append(Item(d["merged_at"], "pr_merged", f"{kind} #{d['number']} {d['title']}", d["repo"], rel, "c0",
                            d["title"]))
        elif mine and _in(d.get("created"), start, end):
            out.append(Item(d["created"], "pr_opened", f"{kind} #{d['number']} {d['title']}", d["repo"], rel, "c0",
                            d["title"]))
        for i, r in enumerate(d.get("reviews") or [], 1):
            if r.get("author") == d.get("me") and _in(r.get("date"), start, end):
                verb = {"APPROVED": "Approved", "CHANGES_REQUESTED": "Requested changes on"}.get(r["state"], "Reviewed")
                out.append(Item(r["date"], "review_given", f"{verb} {kind} #{d['number']} {d['title']}", d["repo"],
                                rel, f"c{i}", d["title"]))
    for p in sorted((ctx.home / "sources/jira").glob("*.json")):
        d = read_raw(p)
        if d.get("deleted"):
            continue
        rel = _rel(ctx, p)
        for t in d.get("transitions") or []:
            if t.get("by_me") and _in(t["date"], start, end):
                done = (t.get("to") or "").lower() in ("done", "closed", "resolved")
                out.append(Item(t["date"], "issue_done" if done else "transition",
                                f"{d['key']} {d['summary']}" + ("" if done else f" → {t['to']}"),
                                d["key"].split("-")[0], rel, "c0", d["summary"]))
    for p in sorted((ctx.home / "sources/drive").glob("*.json")):
        d = read_raw(p)
        if not d.get("deleted") and me.is_me(d.get("modified_by", "")) and _in(d.get("modified"), start, end):
            out.append(Item(d["modified"], "doc_edited", d["title"], "docs", _rel(ctx, p), "c0", d["title"]))
    for p in sorted((ctx.home / "sources/gmail").glob("*.json")):
        d = read_raw(p)
        for i, m in enumerate(d.get("messages") or []):
            if m.get("from_me") and _in(m["date"], start, end):
                to = ", ".join(a.get("name") or a["email"] for a in m.get("to", [])[:2])
                out.append(Item(m["date"], "email_sent", f"{m.get('subject') or '(no subject)'} (to {to})", "email",
                                _rel(ctx, p), f"c{i}", m.get("subject") or ""))
    from archie.derive.meetings import load_meetings

    for m in load_meetings(ctx.home):
        if m.meta.get("status") == "scheduled" and m.meta.get("attendees") and _in(m.meta["start"], start, end) \
                and m.meta["start"] <= ctx.now.isoformat():
            out.append(Item(m.meta["start"], "meeting", m.meta.get("title", ""), "meetings", m.rel_path, "c0",
                            m.meta.get("title", "")))
    return sorted(out, key=lambda i: i.when)
