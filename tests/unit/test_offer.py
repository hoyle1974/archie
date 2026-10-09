"""Offering to start a people file for someone asked about who has none (spec: dig-deeper §4),
and finding mentioned people's evidence by their full name (§4.5)."""

import json
import re

import yaml

from archie.ask.offer import fullest, make_offer, yes_no
from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.people import PeopleDirectory
from archie.llm.backend import FakeBackend
from archie.store.files import read_note
from tests.support.fixtures import by_schema, make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def seed(ctx, header=False):
    write_thread(ctx.home, "koala", [msg("k1", "notifications@koalendar.com", "Workpersontwo Birch (via Koalendar)",
                                         [addr(TEST)], "2026-09-22T20:11:00+00:00",
                                         "Workpersontwo Birch booked a 30 minute call with you.",
                                         subject="New booking", to_me=True, bulk=True)])
    write_thread(ctx.home, "self", [msg("s1", TEST, "Test Testerson", [addr(TEST, "Test Testerson")],
                                        "2026-09-22T21:00:00+00:00", "Video call link for the chat with Workpersontwo.",
                                        subject="Updated video conference: Test Testerson & Workpersontwo Birch",
                                        from_me=True, to_me=True)])
    write_thread(ctx.home, "workperson", [msg("m1", "workperson@acme.example", "Workperson Acorn", [addr(TEST)],
                                         "2026-09-30T22:00:00+00:00", "Thanks for pinging Workpersontwo about onboarding!",
                                         subject="Onboarding", to_me=True)])
    if header:
        write_thread(ctx.home, "direct", [msg("d1", "workpersontwo@example.com", "Workpersontwo Birch", [addr(TEST)],
                                              "2026-09-29T17:00:00+00:00", "Looking forward to starting on Monday.",
                                              subject="Start date", to_me=True)])
    ctx.index.sync()


def items(ctx, *tids):
    out = []
    for t in tids:
        out += [{"path": c["path"], "text": c["text"], "label": c["label"]}
                for c in ctx.index.chunks_of(f"sources/gmail/{t}.json")]
    return out


def cite(quote, shape_key="summary"):
    def answer(system, user, shape, tier):
        ref = next(int(n) for n, body in re.findall(r'<source n="(\d+)"[^>]*>(.*?)</source>', user, re.S)
                   if quote in body)
        if shape.name == "people_facts":
            return {"facts": [{"text": "Booked a call with you", "ref": ref, "quote": quote}]}
        return {"summary": [{"text": "Workperson thanked you for pinging Workpersontwo.",
                             "citations": [{"ref": ref, "quote": quote}]}], "sections": []}
    return answer


def _log(ctx):
    return json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])


def test_yes_and_no_are_matched_in_code():
    for said in ("yes", "Yes!", "sure, go ahead", "ok do it", "yes please", "yep thanks", "start one", "please do",
                 "go for it"):
        assert yes_no(said) is True, said
    for said in ("no", "nope", "No thanks.", "don't", "skip", "nah", "do not", "not now"):
        assert yes_no(said) is False, said
    for said in ("yes but who is she?", "tell me about Workpersontwo", "", "thanks", "yes no"):
        assert yes_no(said) is None, said


def test_the_fullest_form_two_files_use_is_offered(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    found = items(ctx, "koala", "self", "workperson")
    assert fullest("Workpersontwo", found) == "Workpersontwo Birch"
    assert fullest("Workpersontwo", items(ctx, "workperson")) == "Workpersontwo"
    line, pending = make_offer(ctx, ["Workpersontwo"], found)
    assert line == "I don't have a file on Workpersontwo Birch yet. The name is in 3 of your sources. Want me to start one?"
    assert pending["kind"] == "offer_person" and pending["name"] == "Workpersontwo Birch"
    assert pending["aliases"] == ["Workpersontwo"] and pending["options"] == []


def test_one_source_is_not_enough(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    assert make_offer(ctx, ["Workpersontwo"], items(ctx, "workperson")) is None


def test_no_offer_for_me_known_people_declined_names_or_role_accounts(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    found = items(ctx, "koala", "self", "workperson")
    assert make_offer(ctx, ["Test"], found) is None
    assert make_offer(ctx, ["Workperson"], found) is None  # one file only, and a sender
    (ctx.home / "state").mkdir(exist_ok=True)
    (ctx.home / "state/people_declined.yaml").write_text("names: [Workpersontwo Birch]\n")
    assert make_offer(ctx, ["Workpersontwo"], found) is None
    write_thread(ctx.home, "k2", [msg("k2", "notifications@koalendar.com", "Koalendar", [addr(TEST)],
                                      "2026-09-23T10:00:00+00:00", "Koalendar reminder: your call is soon.",
                                      to_me=True, bulk=True)])
    write_thread(ctx.home, "k3", [msg("k3", TEST, "Test Testerson", [addr(TEST)], "2026-09-23T11:00:00+00:00",
                                      "Koalendar sent me two reminders.", from_me=True)])
    ctx.index.sync()
    assert make_offer(ctx, ["Koalendar"], items(ctx, "k2", "k3")) is None


def test_a_via_name_is_a_person(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    _, pending = make_offer(ctx, ["Workpersontwo Birch (via Koalendar)"], items(ctx, "koala", "self"))
    assert pending["name"] == "Workpersontwo Birch" and pending["aliases"] == []


def _flow(tmp_path, header=False):
    fb = FakeBackend(by_schema(understand=understood(question("search", people=["Workpersontwo"], topic="Workpersontwo")),
                               answer=cite("Thanks for pinging Workpersontwo"), answer_check={"helpful": True},
                               people_facts=cite("Workpersontwo Birch booked a 30 minute call")))
    ctx = make_ctx(tmp_path, fb, dig=True)
    seed(ctx, header)
    return ctx, fb


def test_an_answer_ends_with_the_offer_and_yes_starts_the_file(tmp_path):
    ctx, fb = _flow(tmp_path, header=True)
    out = render(ask(ctx, "what about Workpersontwo?"))
    assert out.startswith("Workperson thanked you")
    assert out.endswith("I don't have a file on Workpersontwo Birch yet. The name is in 4 of your sources. "
                        "Want me to start one?")
    assert _log(ctx)["offered"] == "Workpersontwo Birch"
    out = render(ask(ctx, "yes"))
    assert out == "Started a file on Workpersontwo Birch with 1 fact from your mail and calendar."
    note = read_note(ctx.home / "people/workpersontwo_birch.md")
    assert note.meta["origin"] == "mentioned" and note.meta["status"] == "stub"
    assert note.meta["aliases"] == ["Workpersontwo", "workpersontwo@example.com"]  # the header address, not Koalendar's
    assert note.meta["first_seen"].startswith("2026-09-22T20:11")
    assert "Booked a call with you" in note.body
    told = (ctx.home / "journal/told.md").read_text()
    assert '"yes" → Started a file on Workpersontwo Birch' in told
    assert yaml.safe_load((ctx.home / "state/people_enriched.yaml").read_text())["workpersontwo_birch"]
    assert PeopleDirectory.load(ctx.home).find("Workpersontwo") == ["workpersontwo_birch"]


def test_no_is_remembered_and_never_offered_again(tmp_path):
    ctx, fb = _flow(tmp_path)
    ask(ctx, "what about Workpersontwo?")
    assert render(ask(ctx, "no thanks")) == "OK, I won't keep a file on Workpersontwo Birch."
    assert yaml.safe_load((ctx.home / "state/people_declined.yaml").read_text()) == {"names": ["Workpersontwo Birch"]}
    out = render(ask(ctx, "what about Workpersontwo?"))
    assert "Want me to start one?" not in out and "offered" not in _log(ctx)
    assert not (ctx.home / "people/workpersontwo_birch.md").exists()


def test_anything_else_drops_the_offer(tmp_path):
    ctx, fb = _flow(tmp_path)
    ask(ctx, "what about Workpersontwo?")
    fb.replies = by_schema(understand=understood(question("search", topic="onboarding")),
                           answer=cite("Thanks for pinging Workpersontwo"), answer_check={"helpful": True})
    out = render(ask(ctx, "and onboarding?"))
    assert out.startswith("Workperson thanked you")
    seen = [c["user"] for c in fb.calls if c["shape"].name == "understand"][-1]
    assert "Archie just asked: Want me to start a file on Workpersontwo Birch?" in seen  # context for the reply
    assert not (ctx.home / "people/workpersontwo_birch.md").exists()
    assert render(ask(ctx, "yes")) != "Started a file on Workpersontwo Birch; I couldn't confirm any facts yet."
    assert not (ctx.home / "people/workpersontwo_birch.md").exists()  # the offer was dropped


def test_agreeing_in_other_words_starts_the_file_on_the_name_offered(tmp_path):
    ctx, fb = _flow(tmp_path)
    ask(ctx, "what about Workpersontwo?")
    fb.replies = by_schema(understand=understood(part("instruct", action="start_person", target="Workpersontwo Birch")),
                           people_facts={"facts": []})
    assert render(ask(ctx, "yes, start one for her")) == "Started a file on Workpersontwo Birch; I couldn't confirm any facts yet."


def test_a_pronoun_is_not_a_name_to_start_a_file_on(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(part("instruct", action="start_person", target="her"))))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    assert render(ask(ctx, "start a file on her")) == "Who should I start a file on? Say their name."
    assert not list((ctx.home / "people").glob("*.md"))


def test_a_possessive_is_not_part_of_the_name(tmp_path):
    found = [{"path": f"sources/gmail/{i}.json", "text": "Workpersontwo Birch's notes are attached.", "label": ""}
             for i in range(2)]
    assert fullest("Workpersontwo", found) == "Workpersontwo Birch"


def test_a_business_behind_a_role_address_is_not_offered(tmp_path):
    ctx = make_ctx(tmp_path)
    for i in range(2):
        write_thread(ctx.home, f"sa{i}", [msg(f"sa{i}", "support@headphonesrus.example", "HeadphonesRUs Support",
                                              [addr(TEST)], f"2026-09-2{i}T10:00:00+00:00",
                                              "HeadphonesRUs here: try resetting the earbuds.", to_me=True)])
    ctx.index.sync()
    assert make_offer(ctx, ["HeadphonesRUs"], items(ctx, "sa0", "sa1")) is None


def test_start_a_file_on_someone_needs_only_one_source(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(part("instruct", action="start_person", target="Workperson Acorn")),
                               people_facts={"facts": []}))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    (ctx.home / "state").mkdir(exist_ok=True)
    (ctx.home / "state/people_declined.yaml").write_text("names: [Workperson Acorn]\n")
    write_thread(ctx.home, "keith2", [msg("m2", TEST, "Test Testerson", [addr("workperson@acme.example", "Workperson Acorn")],
                                          "2026-09-30T23:00:00+00:00", "Workperson Acorn, see you at standup.",
                                          from_me=True)])
    ctx.index.sync()
    out = render(ask(ctx, "start a file on Workperson Acorn"))
    assert out == "Started a file on Workperson Acorn; I couldn't confirm any facts yet."
    meta = read_note(ctx.home / "people/workperson_acorn.md").meta
    assert meta["origin"] == "mentioned" and "workperson@acme.example" in meta["aliases"]
    assert yaml.safe_load((ctx.home / "state/people_declined.yaml").read_text()) == {"names": []}


def test_start_a_file_with_no_sources_writes_nothing(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(part("instruct", action="start_person", target="Zebulon"))))
    ctx = make_ctx(tmp_path, fb)
    out = render(ask(ctx, "start a file on Zebulon"))
    assert out == "I couldn't find Zebulon in your mail or calendar, so I haven't started a file."
    assert not list((ctx.home / "people").glob("*.md"))


def test_mentioned_people_are_found_by_full_name_not_first_name(tmp_path):
    from archie.ask.evidence import person_evidence
    from archie.store.files import Note, write_note

    ctx = make_ctx(tmp_path)
    seed(ctx)
    write_note(ctx.home / "people/workpersontwo_birch.md", Note(meta={
        "entity_id": "workpersontwo_birch", "name": "Workpersontwo Birch", "aliases": ["Workpersontwo"], "status": "stub",
        "origin": "mentioned"}, body="## My notes\n\n"))
    ctx.index.sync()
    paths = {c["path"] for c in person_evidence(ctx, "workpersontwo_birch")}
    assert paths == {"sources/gmail/koala.json", "sources/gmail/self.json"}  # not Workperson's "Workpersontwo"
    assert PeopleDirectory.load(ctx.home).mention_names("workpersontwo_birch") == ["Workpersontwo Birch"]


# -- a file holding only the user's notes ("bare") -------------------------------------

def _bare(ctx, name="Workpersontwo"):
    from archie.store.files import Note, write_note

    write_note(ctx.home / f"people/{name.lower()}.md", Note(
        meta={"entity_id": name.lower(), "name": name, "aliases": [], "org": None, "status": "known"},
        body=f"## My notes\n- I will meet {name} next week _(you said, Oct 5)_\n"))
    ctx.index.sync()


def test_a_bare_file_gets_the_fuller_name_two_sources_use(tmp_path):
    from archie.ask.offer import fuller_name

    ctx = make_ctx(tmp_path, FakeBackend(lambda *a: {}))
    seed(ctx)
    _bare(ctx)
    d = PeopleDirectory.load(ctx.home)
    full, sources = fuller_name(ctx, d, "workpersontwo")
    assert full == "Workpersontwo Birch" and len(sources) == 2  # Workperson's "Workpersontwo" alone doesn't count


def test_no_fuller_name_once_declined_or_when_the_file_has_an_address(tmp_path):
    from archie.ask.offer import _set_declined, fuller_name

    ctx = make_ctx(tmp_path, FakeBackend(lambda *a: {}))
    seed(ctx)
    _bare(ctx)
    _set_declined(ctx, ["Workpersontwo Birch"])
    assert fuller_name(ctx, PeopleDirectory.load(ctx.home), "workpersontwo") is None
    _set_declined(ctx, [])
    note = read_note(ctx.home / "people/workpersontwo.md")
    note.meta["aliases"] = ["workpersontwo@example.com"]
    from archie.store.files import write_note

    write_note(ctx.home / "people/workpersontwo.md", note)
    assert fuller_name(ctx, PeopleDirectory.load(ctx.home), "workpersontwo") is None  # found by address already


def test_mention_names_cover_people_without_an_address(tmp_path):
    d = PeopleDirectory()
    d.add("acorn", {"name": "Acorn", "full_name": "Acorn Testerson", "aliases": []})
    d.add("workperson", {"name": "Workperson Acorn", "aliases": ["workperson@acme.example"]})
    assert d.mention_names("acorn") == ["Acorn Testerson"]  # never the single word "Acorn"
    assert d.mention_names("workperson") == []  # found by address instead


def test_start_a_file_fills_in_the_bare_one_instead_of_a_second(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(part("instruct", action="start_person", target="Workpersontwo Birch")),
        people_facts=cite("Workpersontwo Birch booked a 30 minute call with you."))))
    seed(ctx)
    _bare(ctx)
    out = render(ask(ctx, "start a file on Workpersontwo Birch"))
    assert out.startswith("Added what your sources say about Workpersontwo Birch to your file on Workpersontwo, with 1 fact")
    note = read_note(ctx.home / "people/workpersontwo.md")
    assert note.meta["name"] == "Workpersontwo" and note.meta["full_name"] == "Workpersontwo Birch"
    assert not (ctx.home / "people/workpersontwo_birch.md").exists()
