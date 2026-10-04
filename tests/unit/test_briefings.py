from datetime import datetime, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.briefings.build import build_briefing, pick_meeting
from archie.connectors.calendar import normalize_event
from archie.derive.loops import Loop, save_loop
from archie.derive.meetings import derive_meetings
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, write_raw
from tests.support.fake_google import cal_event
from tests.support.fixtures import by_schema, TEST, make_ctx, question, understood
from tests.support.raw import addr, msg, write_thread

NOW = datetime(2026, 10, 1, 20, 45, tzinfo=timezone.utc)  # 1:45 PM PDT


def seed(ctx):
    review = cal_event("ev1", "Design Review: Auth Redesign", "2026-10-01T21:00:00Z", "2026-10-01T21:45:00Z",
                       attendees=[("test@acme.example", "Test"), ("alex@acme.example", "Alex Rivera"),
                                  ("priya@acme.example", "Priya Sharma")], description="Agenda: Redis cluster")
    later = cal_event("ev2", "Lunch w/ Ken", "2026-10-01T23:00:00Z", "2026-10-01T23:30:00Z",
                      attendees=[("test@acme.example", "Test"), ("ken@acme.example", "Ken Ito")])
    paths = []
    for ev in (review, later):
        p = ctx.home / f"sources/calendar/{ev['id']}.json"
        write_raw(p, normalize_event(ev, TEST))
        paths.append(p)
    paths.append(write_thread(ctx.home, "t1", [
        msg("m1", "alex@acme.example", "Alex Rivera", [addr("test@acme.example")], "2026-09-30T18:00:00+00:00",
            "Merged PR 412, the redis connection pool fix. Can you review my fallback logic by today?",
            subject="Redis pool", to_me=True)]))
    derive_people(ctx, paths)
    derive_meetings(ctx, paths)
    meta = {"loop_id": "loop-1", "kind": "asked_of_me", "status": "open", "counterpart": "alex_rivera",
            "counterpart_name": "Alex Rivera", "summary": "Review Alex's Redis fallback logic",
            "created_at": "2026-09-30T18:00:00+00:00", "due": "2026-10-01", "snoozed_until": None, "thread": "t1",
            "addressed": "to", "sources": [{"file": "sources/gmail/t1.json", "chunk": "c0",
                                           "quote": "Can you review my fallback logic by today?"}], "closed_by": None}
    save_loop(ctx.home, Loop("loop-1", "loops/2026/loop-1.md", Note(meta=meta, body="")))
    ctx.index.sync()


def synth(system, user, schema, tier):
    ref = next(int(line[1:line.index("]")]) for line in user.splitlines() if line.startswith("[") and "Redis pool" in line)
    return {"summary": [{"text": "Alex merged the Redis pool fix and wants your review of the fallback logic.",
                         "citations": [{"ref": ref, "quote": "Merged PR 412, the redis connection pool fix"}]}],
            "sections": [{"heading": "What changed", "items": [
                {"text": "PR 412 merged.", "citations": [{"ref": ref, "quote": "Merged PR 412"}]}]}]}


def test_pick_next_meeting_and_by_time_and_title(tmp_path):
    ctx = make_ctx(tmp_path, now=NOW)
    seed(ctx)
    assert pick_meeting(ctx, None).meta["title"] == "Design Review: Auth Redesign"
    assert pick_meeting(ctx, "4pm").meta["title"] == "Lunch w/ Ken"
    assert pick_meeting(ctx, "lunch").meta["title"] == "Lunch w/ Ken"


def test_briefing_has_header_people_open_items_and_cited_summary(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=synth)), now=NOW)
    seed(ctx)
    meeting = pick_meeting(ctx, None)
    b = build_briefing(ctx, meeting)
    out = render(b.answer)
    lines = out.splitlines()
    assert lines[0] == "2:00 PM · Design Review: Auth Redesign · 45 min"
    assert lines[1].startswith("Alex merged the Redis pool fix")
    assert "Alex Rivera" in out and "Priya Sharma" in out
    assert "Review Alex's Redis fallback logic" in out and "due today" in out
    assert "PR 412 merged." in out
    saved = list((ctx.home / "briefings").rglob("*.md"))
    assert len(saved) == 1 and "Design Review" in saved[0].read_text()


def test_unchanged_inputs_reuse_saved_briefing(tmp_path):
    fb = FakeBackend(by_schema(answer=synth))
    ctx = make_ctx(tmp_path, fb, now=NOW)
    seed(ctx)
    m = pick_meeting(ctx, None)
    build_briefing(ctx, m)
    again = build_briefing(ctx, m)
    assert len(fb.calls) == 1 and again.reused


def test_brief_intent_end_to_end(tmp_path):
    route = understood(question("brief", meeting="next"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=route, answer=synth)), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "prep me for my next meeting"))
    assert out.startswith("2:00 PM · Design Review")


def test_no_upcoming_meeting(tmp_path):
    route = understood(question("brief"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=route)), now=NOW)
    assert "no upcoming meetings" in render(ask(ctx, "prep me")).lower()


def test_linked_doc_is_in_the_packet(tmp_path):
    seen = {}

    def capture(system, user, schema, tier):
        seen["user"] = user
        return synth(system, user, schema, tier)

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer=capture)), now=NOW)
    seed(ctx)
    write_raw(ctx.home / "sources/drive/doc1.json", {"id": "doc1", "title": "Auth_Migration_Draft",
                                                    "modified": "2026-10-01T20:15:00+00:00", "modified_by": "alex@acme.example",
                                                    "owners": ["alex@acme.example"], "text": "Move session tokens to Redis."})
    m = pick_meeting(ctx, None)
    m.meta["linked_docs"] = ["doc1"]
    ctx.index.sync()
    build_briefing(ctx, m)
    assert "Attached Doc: Auth_Migration_Draft" in seen["user"] and "Move session tokens to Redis." in seen["user"]


def test_standup_has_code_computed_yesterday_today_blockers(tmp_path):
    from tests.unit.test_activity import seed as seed_activity

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(answer={"summary": [], "sections": []})),
                   now=datetime(2026, 10, 1, 16, 45, tzinfo=timezone.utc))  # Thu 9:45 AM PDT
    seed_activity(ctx)
    from archie.store.files import write_raw as wr
    wr(ctx.home / "sources/jira/ENG-500.json", {
        "key": "ENG-500", "summary": "Rotate signing keys", "type": "Task", "status": "In Progress",
        "status_category": "indeterminate", "assignee": {"id": "acc-test", "name": "Test", "email": ""},
        "reporter": {"id": "p", "name": "P", "email": ""}, "assignee_me": True, "priority": "", "due": None,
        "created": "2026-09-25T00:00:00+00:00", "updated": "2026-09-30T00:00:00+00:00", "description": "",
        "comments": [], "transitions": [], "url": "u"})
    ev = cal_event("su", "Daily Standup", "2026-10-01T17:00:00Z", "2026-10-01T17:15:00Z",
                   attendees=[("test@acme.example", "Test"), ("alex@acme.example", "Alex")], recurring="su")
    p = ctx.home / "sources/calendar/su.json"
    write_raw(p, normalize_event(ev, TEST))
    derive_meetings(ctx, [p])
    ctx.index.sync()
    from archie.ask.render import render as r
    out = r(build_briefing(ctx, pick_meeting(ctx, None)).answer)
    assert "Yesterday" in out and "Lower token TTL to 15m" in out and "Approved PR #412 Fix redis pool" in out
    assert "Today" in out and "ENG-500 Rotate signing keys (In Progress)" in out
