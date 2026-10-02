from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.dedupe import find_duplicates, open_questions
from archie.derive.loops import Loop, load_loops, save_loop
from archie.derive.people import PeopleDirectory, derive_people, merge_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, read_note
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def people(ctx, *pairs):
    msgs = [msg(f"m{i}", email, name, [addr(TEST)], "2026-10-01T00:00:00+00:00", "hi", to_me=True)
            for i, (email, name) in enumerate(pairs)]
    derive_people(ctx, [write_thread(ctx.home, "t1", msgs)])


def test_same_full_name_merges_automatically_and_says_so(tmp_path):
    ctx = make_ctx(tmp_path)
    people(ctx, ("goodspouse@home.example", "Goodspouse Testerson"), ("gs@work.example", "Goodspouse Testerson"))
    find_duplicates(ctx)
    d = PeopleDirectory.load(ctx.home)
    [eid] = d.find("Goodspouse Testerson")
    assert {"goodspouse@home.example", "gs@work.example"} <= set(d.identifiers(eid))
    assert any("Merged" in q["text"] for q in open_questions(ctx.home, include_notices=True))


def test_partial_name_match_becomes_a_question_then_yes_merges(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))  # a plain yes needs no model call
    people(ctx, ("belle@x.example", "Goodspouse Testerson"), ("gls@y.example", "Goodspouse Belle Testerson"))
    find_duplicates(ctx)
    [q] = open_questions(ctx.home)
    assert "Goodspouse Testerson" in q["text"] and "Goodspouse Belle Testerson" in q["text"]
    out = render(ask(ctx, "yes"))
    assert "merged" in out.lower()
    assert len(PeopleDirectory.load(ctx.home).find("Goodspouse")) == 1
    assert open_questions(ctx.home) == []


def test_no_is_remembered_and_never_asked_again(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    people(ctx, ("a@x.example", "Sam Lee"), ("b@y.example", "Sam Lee Jr"))
    find_duplicates(ctx)
    render(ask(ctx, "no, different people"))
    find_duplicates(ctx)
    assert open_questions(ctx.home) == []
    assert len(PeopleDirectory.load(ctx.home).meta) == 2


def test_merge_moves_aliases_notes_and_loops(tmp_path):
    ctx = make_ctx(tmp_path)
    people(ctx, ("belle@x.example", "Goodspouse Testerson"), ("gls@y.example", "Goodspouse Belle Testerson"))
    d = PeopleDirectory.load(ctx.home)
    a, b = d.find("Goodspouse Testerson")[0], d.find("Goodspouse Belle Testerson")[0]
    note = read_note(ctx.home / f"people/{b}.md")
    note.body = note.body.replace("## My notes\n", "## My notes\n- Goes by Belle online.\n")
    from archie.store.files import write_note
    write_note(ctx.home / f"people/{b}.md", note)
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta={"loop_id": "l1", "counterpart": b,
                                                                   "counterpart_name": "Goodspouse Belle Testerson",
                                                                   "status": "open"}, body="")))
    merge_people(ctx.home, a, b)
    kept = read_note(ctx.home / f"people/{a}.md")
    assert "gls@y.example" in kept.meta["aliases"] and "Goes by Belle online." in kept.body
    assert read_note(ctx.home / f"people/{b}.md").meta["status"] == "merged"
    assert load_loops(ctx.home)[0].meta["counterpart"] == a


def test_several_questions_use_the_model_to_match_the_reply(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(clarify={"answers": [{"question": 2, "same": True}]})))
    people(ctx, ("a@x.example", "Sam Lee"), ("b@y.example", "Sam Lee Jr"),
           ("c@x.example", "Kim Park"), ("d@y.example", "Kim Park Lee"))
    find_duplicates(ctx)
    qs = open_questions(ctx.home)
    assert len(qs) == 2
    out = render(ask(ctx, "yes, the Kim ones are the same"))
    assert "merged" in out.lower() and len(open_questions(ctx.home)) == 1
