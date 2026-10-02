from datetime import datetime, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

NOW = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)


def route(intent):
    return {"intent": intent, "params": {"people": [], "since": None, "until": None, "topic": None,
                                         "meeting": None, "text": None}}


def seed(ctx):
    write_thread(ctx.home, "t1", [msg("m1", "sarah@x.example", "Sarah Jones", [addr("test@acme.example")],
                                      "2026-09-28T16:30:00+00:00", "can you review the Redis fallback patch", to_me=True)])
    ctx.index.sync()
    for i, (kind, who, summary, due, created) in enumerate([
            ("asked_of_me", "Sarah Jones", "Review the Redis fallback patch", "2026-10-02", "2026-09-28T16:30:00+00:00"),
            ("waiting_on", "Priya Sharma", "SSO launch date", None, "2026-09-27T16:30:00+00:00")], 1):
        meta = {"loop_id": f"loop-{i}", "kind": kind, "status": "open", "counterpart": who.lower().replace(" ", "_"),
                "counterpart_name": who, "summary": summary, "created_at": created, "due": due,
                "snoozed_until": None, "thread": "t1", "addressed": "to",
                "sources": [{"file": "sources/gmail/t1.json", "chunk": "c0", "quote": "review the Redis fallback patch"}],
                "closed_by": None}
        save_loop(ctx.home, Loop(f"loop-{i}", f"loops/2026/loop-{i}.md", Note(meta=meta, body="")))


def test_loops_listing_needs_no_synthesis_and_leads_with_most_urgent(tmp_path):
    fb = FakeBackend(by_schema(route=route("loops")))
    ctx = make_ctx(tmp_path, fb, now=NOW)
    seed(ctx)
    out = render(ask(ctx, "what do I owe people?"))
    first = out.splitlines()[0]
    assert first.startswith("You have 1 open item. Most urgent: Review the Redis fallback patch, for Sarah Jones")
    assert "Sarah Jones" in out and "due in 1 day" in out
    assert "[1]" in out
    assert [c["schema"]["title"] for c in fb.calls] == ["route"]


def test_general_question_lists_everything(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loops"))), now=NOW)
    seed(ctx)
    assert render(ask(ctx, "what's open?")).startswith("You have 2 open items.")


def test_waiting_question_filters_to_waiting_on(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loops"))), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "what am I waiting on?"))
    assert "SSO launch date" in out and "Redis" not in out


def test_no_loops_is_said_plainly(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loops"))), now=NOW)
    assert "nothing open" in render(ask(ctx, "what do I owe?")).lower()


def test_loop_update_marks_done_by_user_word(tmp_path):
    upd = {"action": "done", "loops": [1], "until": None, "reason": None}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loop_update"), loop_update=upd)), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "done with Sarah's review"))
    assert "Marked done" in out and "Review the Redis fallback patch" in out
    loop = next(lp for lp in load_loops(ctx.home) if lp.loop_id == "loop-1")
    assert loop.meta["status"] == "done" and "user" in loop.meta["closed_by"]


def test_loop_update_snooze_sets_date(tmp_path):
    upd = {"action": "snooze", "loops": [2], "until": "2026-10-05", "reason": None}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loop_update"), loop_update=upd)), now=NOW)
    seed(ctx)
    render(ask(ctx, "snooze the SSO one till Monday"))
    loop = next(lp for lp in load_loops(ctx.home) if lp.loop_id == "loop-2")
    assert loop.meta["status"] == "snoozed" and loop.meta["snoozed_until"] == "2026-10-05"


def test_loop_update_with_no_match_lists_items(tmp_path):
    upd = {"action": "done", "loops": [], "until": None, "reason": None}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route("loop_update"), loop_update=upd)), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "done with the thing"))
    assert "couldn't tell which" in out and "Review the Redis fallback patch" in out


def test_second_dismissal_from_same_sender_mutes_them_visibly(tmp_path):
    import yaml

    from archie.config import load_config

    ctx = make_ctx(tmp_path, now=NOW)
    seed(ctx)
    for i in (3, 4):
        meta = {"loop_id": f"loop-{i}", "kind": "asked_of_me", "status": "open", "counterpart": "recruiter@x.example",
                "counterpart_name": "Recruiter", "summary": f"Reply to recruiter {i}", "created_at": "2026-09-30T00:00:00+00:00",
                "due": None, "snoozed_until": None, "thread": "t", "addressed": "to", "sources": [], "closed_by": None}
        save_loop(ctx.home, Loop(f"loop-{i}", f"loops/2026/loop-{i}.md", Note(meta=meta, body="")))
    outs = []
    for _ in range(2):
        ctx.backend = FakeBackend(by_schema(route=route("loop_update"), loop_update=lambda s, u, sc, t: {
            "action": "dismiss", "loops": [next(i for i, line in enumerate(u.split("Items:\n")[1].splitlines(), 1)
                                                if "recruiter" in line and "[open]" in line)],
            "until": None, "reason": "not a loop"}))
        outs.append(render(ask(ctx, "that's not a loop")))
    assert "won't track" not in outs[0] and "won't track" in outs[1]
    cfg = yaml.safe_load((ctx.home / "config.yaml").read_text())
    assert cfg["loops"]["mute"] == ["recruiter@x.example"]
    assert "recruiter@x.example" in load_config(ctx.home)["loops"]["mute"]


def test_muted_sender_mail_is_never_sent_to_llm(tmp_path):
    from archie.derive.loops import derive_loops

    ctx = make_ctx(tmp_path, now=NOW)  # FakeBackend([]) would raise if called
    ctx.config["loops"]["mute"] = ["@x.example"]
    p = write_thread(ctx.home, "t9", [msg("m9", "sam@x.example", "Sam", [addr("test@acme.example")],
                                          "2026-09-30T00:00:00+00:00", "can you call me?", to_me=True)])
    derive_loops(ctx, [p])
    assert load_loops(ctx.home) == []
