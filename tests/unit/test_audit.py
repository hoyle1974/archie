from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.audit import MAX_OPEN, audit
from archie.derive.dedupe import open_questions, load_questions, save_questions
from archie.derive.loops import Loop, load_loops, save_loop
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread


def loop(ctx, lid, status="open", due=None, closed_by=None):
    meta = {"loop_id": lid, "kind": "asked_of_me", "status": status, "counterpart": "sam", "counterpart_name": "Sam",
            "summary": f"Do {lid}", "created_at": "2026-09-01T00:00:00+00:00", "due": due, "snoozed_until": None,
            "thread": "t", "addressed": "to", "sources": [], "closed_by": closed_by}
    save_loop(ctx.home, Loop(lid, f"loops/2026/{lid}.md", Note(meta=meta, body="")))


def test_probably_done_becomes_a_question_and_yes_closes_it(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    loop(ctx, "l1", status="maybe_done", closed_by={"file": "sources/github/x/pr-1.json", "chunk": "c1", "quote": "q"})
    audit(ctx)
    [q] = open_questions(ctx.home)
    assert q["kind"] == "loop_done" and "Did you finish: Do l1 (Sam)?" in q["text"]
    out = render(ask(ctx, "yes"))
    assert "Marked done" in out and load_loops(ctx.home)[0].meta["status"] == "done"


def test_no_reopens_a_probably_done_item(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    loop(ctx, "l1", status="maybe_done", closed_by={"file": "f", "chunk": "c0", "quote": "q"})
    audit(ctx)
    render(ask(ctx, "no"))
    m = load_loops(ctx.home)[0].meta
    assert m["status"] == "open" and m["closed_by"] is None


def test_stale_item_question(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    loop(ctx, "l2", due="2026-09-10")
    audit(ctx)
    [q] = open_questions(ctx.home)
    assert q["kind"] == "loop_stale" and "Do you still need to: Do l2 (Sam)?" in q["text"]
    render(ask(ctx, "yes"))
    m = load_loops(ctx.home)[0].meta
    assert m["status"] == "open" and m["due"] is None


def test_unnamed_person_is_asked_about_and_clears_itself(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [write_thread(ctx.home, "t1", [
        msg("m1", "zz9@x.example", "", [addr("test@acme.example")], "2026-10-01T00:00:00+00:00", "hi", to_me=True)])])
    audit(ctx)
    [q] = open_questions(ctx.home)
    assert q["kind"] == "who_is" and "Who is zz9@x.example?" in q["text"]
    from archie.store.files import read_note, write_note
    p = next((ctx.home / "people").glob("*.md"))
    note = read_note(p)
    note.meta["relationship"] = "plumber"
    write_note(p, note)
    audit(ctx)
    assert open_questions(ctx.home) == []


def test_never_more_than_max_open(tmp_path):
    ctx = make_ctx(tmp_path)
    for i in range(MAX_OPEN + 4):
        loop(ctx, f"s{i}", due="2026-09-10")
    audit(ctx)
    assert len(open_questions(ctx.home)) == MAX_OPEN
