from archie.derive.enrich import enrich_people, parse_facts
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.store.fence import get_fence
from archie.store.files import read_note, write_note
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def seed(ctx):
    p = write_thread(ctx.home, "t1", [msg("m1", "workperson@ow.example", "Workperson Acorn", [addr(TEST)],
                                          "2026-10-01T00:00:00+00:00",
                                          "Welcome aboard! I run people ops at Overwatch and will get your laptop shipped.",
                                          to_me=True)])
    derive_people(ctx, [p])
    ctx.index.sync()


def facts(*items):
    return {"facts": [{"text": t, "ref": 1, "quote": q} for t, q in items]}


def test_cited_facts_land_in_fence_and_user_notes_survive(tmp_path):
    calls = []

    def reply(s, u, sc, t):
        calls.append(u)
        return facts(("Runs people ops at Overwatch", "I run people ops at Overwatch"),
                     ("Is a dragon", "breathes fire"))

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=reply)))
    seed(ctx)
    path = ctx.home / "people/workperson_acorn.md"
    note = read_note(path)
    note.body = note.body.replace("## My notes\n", "## My notes\nGreat guy.\n")
    write_note(path, note)
    enrich_people(ctx)
    body = read_note(path).body
    assert "Great guy." in body
    fence = get_fence(body)
    assert "- Runs people ops at Overwatch [1]" in fence and "dragon" not in fence
    assert parse_facts(fence)[0]["file"] == "sources/gmail/t1.json"
    enrich_people(ctx)  # nothing new: no second call
    assert len(calls) == 1


def test_facts_accumulate_without_duplicates(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=facts(("Runs people ops at Overwatch",
                                                                         "I run people ops at Overwatch")))))
    seed(ctx)
    enrich_people(ctx)
    write_thread(ctx.home, "t2", [msg("m2", "workperson@ow.example", "Workperson Acorn", [addr(TEST)], "2026-10-02T00:00:00+00:00",
                                      "I also coordinate background checks.", to_me=True)])
    ctx.index.sync()
    from datetime import datetime, timezone
    ctx.now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    ctx.backend = FakeBackend(by_schema(people_facts={"facts": [
        {"text": "Runs people ops at Overwatch", "ref": 2, "quote": "I run people ops at Overwatch"},
        {"text": "Coordinates background checks", "ref": 1, "quote": "I also coordinate background checks"}]}))
    enrich_people(ctx)
    fence = get_fence(read_note(ctx.home / "people/workperson_acorn.md").body)
    assert fence.count("- Runs people ops") == 1 and "Coordinates background checks" in fence


def test_people_deriver_keeps_facts(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=facts(("Runs people ops at Overwatch",
                                                                         "I run people ops at Overwatch")))))
    seed(ctx)
    enrich_people(ctx)
    p = write_thread(ctx.home, "t3", [msg("m3", "workperson@ow.example", "Workperson Acorn", [addr(TEST)],
                                          "2026-10-02T00:00:00+00:00", "hi", to_me=True)])
    derive_people(ctx, [p])
    fence = get_fence(read_note(ctx.home / "people/workperson_acorn.md").body)
    assert "Runs people ops at Overwatch [1]" in fence and "last interaction 2026-10-02" in fence


def test_facts_show_in_who_at_a_glance(tmp_path):
    from archie.ask.intents.who import person_lines
    from archie.derive.people import PeopleDirectory

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=facts(("Runs people ops at Overwatch",
                                                                         "I run people ops at Overwatch")))))
    seed(ctx)
    enrich_people(ctx)
    d = PeopleDirectory.load(ctx.home)
    lines = person_lines(d, "workperson_acorn", [], d.facts(ctx.home, "workperson_acorn"))
    assert "Known for: Runs people ops at Overwatch" in lines


def test_a_person_whose_reply_keeps_failing_stops_costing_calls(tmp_path):
    from archie.derive.failures import MAX_TRIES

    fb = FakeBackend(by_schema(people_facts="FACT Runs people ops"))  # no cite: unreadable
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    for _ in range(MAX_TRIES + 2):
        enrich_people(ctx)
    assert len(fb.calls) == MAX_TRIES
