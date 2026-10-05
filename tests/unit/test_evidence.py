from archie.ask.evidence import person_evidence
from archie.derive.people import PeopleDirectory, derive_people
from archie.store.files import Note, write_note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

ME, LEE = "test@acme.example", "lee@park.example"


def seed(ctx, copied=15):
    paths = [write_thread(ctx.home, "own", [msg("o1", LEE, "Lee Park", [addr(ME)], "2026-09-01T10:00:00+00:00",
                                                "I lead the data platform team.", to_me=True)])]
    paths += [write_thread(ctx.home, f"cc{i}", [msg(f"c{i}", "hr@acme.example", "HR", [addr(ME)],
                                                    f"2026-09-{10 + i:02d}T10:00:00+00:00", f"Benefits form {i}.",
                                                    cc=[addr(LEE, "Lee Park")], to_me=True)])
              for i in range(copied)]
    derive_people(ctx, paths)
    ctx.index.sync()
    return PeopleDirectory.load(ctx.home).by_email(LEE)


def test_own_messages_come_before_newer_copied_ones(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    got = person_evidence(ctx, eid, max_items=5)
    assert got[0]["path"] == "sources/gmail/own.json"
    assert len(got) == 5


def test_a_topic_ranks_first(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    got = person_evidence(ctx, eid, topic="Benefits form 3", max_items=3)
    assert got[0]["path"] == "sources/gmail/cc3.json"


def test_budget_skips_a_chunk_too_big_but_keeps_going(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx, copied=3)
    got = person_evidence(ctx, eid, max_chars=200)
    assert got and sum(len(c["text"]) for c in got) <= 200


def test_person_without_addresses_has_no_evidence(tmp_path):
    ctx = make_ctx(tmp_path)
    write_note(ctx.home / "people/acorn.md", Note(meta={"entity_id": "acorn", "name": "Acorn", "aliases": []},
                                                  body="## My notes\n- Acorn is three. _(you said, Oct 4)_\n"))
    assert person_evidence(ctx, "acorn") == []


def _signed(ctx, n=8):
    sig = "\n-- \nLee Park\nDirector of Engineering\nPark Data"
    paths = [write_thread(ctx.home, f"s{i}", [msg(f"s{i}", LEE, "Lee Park", [addr(ME)],
                                                  f"2026-09-{10 + i:02d}T10:00:00+00:00",
                                                  f"Engineering update number {i}.{sig}", to_me=True)])
             for i in range(n)]
    derive_people(ctx, paths)
    ctx.index.sync()
    return PeopleDirectory.load(ctx.home).by_email(LEE)


def test_the_same_signature_takes_one_slot(tmp_path):
    ctx = make_ctx(tmp_path)
    got = person_evidence(ctx, _signed(ctx), max_items=6)
    assert [c["chunk_id"] for c in got].count("s0") == 1 and len(got) == 6
    assert got[0]["path"] == "sources/gmail/s7.json"


def test_search_shows_the_same_signature_once(tmp_path):
    from archie.index.search import search

    ctx = make_ctx(tmp_path)
    _signed(ctx)
    hits = search(ctx.index, "Lee engineering", k=8)
    assert sum(h.chunk_id.startswith("s") for h in hits) <= 1
