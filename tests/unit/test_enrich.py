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


def seed_family(ctx):
    """Goodspouse writes about Childone, whom the user has said is their child, never "son"."""
    paths = [write_thread(ctx.home, "g1", [msg("m1", "gid@x.example", "Childone Testerson", [addr(TEST)],
                                               "2026-09-29T00:00:00+00:00", "hi", to_me=True)]),
             write_thread(ctx.home, "g2", [msg("m2", "goodspouse@x.example", "Goodspouse Testerson", [addr(TEST)],
                                               "2026-09-30T00:00:00+00:00",
                                               "My son Childone has his IEP meeting Wednesday.", to_me=True)])]
    derive_people(ctx, paths)
    p = ctx.home / "people/childone_testerson.md"
    note = read_note(p)
    note.meta.update(relationship="child", identity="non-binary", pronouns="he/him", avoid=["boy", "son"])
    write_note(p, note)
    ctx.index.sync()
    return ctx.home / "people/goodspouse_testerson.md"


def test_facts_about_one_person_respect_what_the_user_said_about_others(tmp_path):
    prompts = []

    def reply(s, u, sc, t):
        prompts.append(u)
        return facts(("Mother of your son Childone", "My son Childone"),
                     ("Attends Childone's IEP meetings", "Childone has his IEP meeting"))

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=reply)))
    goodspouse = seed_family(ctx)
    enrich_people(ctx)
    fence = get_fence(read_note(goodspouse).body)
    assert "Attends Childone's IEP meetings" in fence
    assert "son" not in fence.split("<!-- archie:citations")[0]
    assert any("Childone Testerson: your child" in u and "never call them: boy, son" in u for u in prompts)


def test_an_old_fact_using_a_ruled_out_word_is_redone(tmp_path):
    from archie.derive.people import render_facts
    from archie.store.fence import set_fence

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=facts(
        ("Attends Childone's IEP meetings", "Childone has his IEP meeting")))))
    goodspouse = seed_family(ctx)
    enrich_people(ctx)
    note = read_note(goodspouse)
    note.body = set_fence(note.body, render_facts(note.meta, [
        {"text": "Advocates for your son's IEP", "file": "sources/gmail/g2.json", "chunk": "c0",
         "quote": "My son Childone has his IEP meeting"}]))
    write_note(goodspouse, note)
    enrich_people(ctx)  # no new mail, but the old fact must go
    fence = get_fence(read_note(goodspouse).body)
    assert "your son" not in fence and "Attends Childone's IEP meetings" in fence


def test_a_person_whose_reply_keeps_failing_stops_costing_calls(tmp_path):
    from archie.derive.failures import MAX_TRIES

    fb = FakeBackend(by_schema(people_facts="FACT Runs people ops"))  # no cite: unreadable
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    for _ in range(MAX_TRIES + 2):
        enrich_people(ctx)
    assert len(fb.calls) == MAX_TRIES


def test_old_contacts_are_written_in_the_past_tense_and_quotes_kept_plain(tmp_path):
    systems = []

    def reply(s, u, sc, t):
        systems.append(s)
        return {"facts": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=reply)))
    p = write_thread(ctx.home, "t9", [msg("m9", "nick@support.example", "Nick", [addr(TEST)],
                                          "2023-07-17T14:47:09+00:00", "We are actively working on resolving it.",
                                          to_me=True)])
    derive_people(ctx, [p])
    ctx.index.sync()
    enrich_people(ctx)
    assert "from 2023, over a year ago" in systems[0] and "past tense" in systems[0]
    assert "Never cite a passage about an accusation" in systems[0]
    seed(ctx)  # Workperson wrote this week: no past-tense rule
    enrich_people(ctx)
    assert "past tense" not in systems[-1]


def test_new_instructions_redo_every_dossier_from_scratch(tmp_path, monkeypatch):
    from archie.derive import enrich

    replies = [facts(("Mother of your child", "Welcome aboard")),
               facts(("Runs people ops at Overwatch", "I run people ops at Overwatch"))]
    calls = []

    def reply(s, u, sc, t):
        calls.append(u)
        return replies[len(calls) - 1]

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=reply)))
    seed(ctx)
    enrich_people(ctx)
    enrich_people(ctx)
    assert len(calls) == 1  # nothing new: no second call
    monkeypatch.setattr(enrich, "INSTRUCTIONS_VERSION", enrich.INSTRUCTIONS_VERSION + 1)
    enrich_people(ctx)
    assert len(calls) == 2
    texts = [f["text"] for f in parse_facts(get_fence(read_note(ctx.home / "people/workperson_acorn.md").body))]
    assert texts == ["Runs people ops at Overwatch"]  # the old instructions' fact is gone
