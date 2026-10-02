from archie.ask.synthesize import people_context
from archie.derive.enrich import enrich_people
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.llm.verify import Packet
from archie.store.fence import get_fence
from archie.store.files import read_note, write_note
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread


def seed(ctx):
    derive_people(ctx, [write_thread(ctx.home, "t1", [
        msg("m1", "gid@x.example", "Childone Testerson", [addr("test@acme.example")], "2026-10-01T00:00:00+00:00",
            "hi dad", to_me=True)])])
    p = ctx.home / "people/childone_testerson.md"
    note = read_note(p)
    note.meta.update(relationship="child", pronouns="they/them", identity="non-binary")
    write_note(p, note)
    return p


def test_every_answer_gets_stated_facts_for_people_it_mentions(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    packet = Packet()
    packet.add("sources/gmail/t9.json", "c0", "Goodspouse wrote: my son Childone has an IEP meeting.")
    ctx_text = people_context(ctx, packet)
    assert "Childone Testerson: your child; non-binary; pronouns they/them" in ctx_text
    assert "override" in ctx_text


def test_no_people_mentioned_means_no_context(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    packet = Packet()
    packet.add("x.md", "c0", "Weather is nice.")
    assert people_context(ctx, packet) == ""


def test_remember_resets_auto_facts_and_enrichment_gets_ground_truth(tmp_path):
    seen = {}

    def facts(system, user, schema, tier):
        seen["system"] = system
        return {"facts": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(people_facts=facts)))
    p = seed(ctx)
    note = read_note(p)
    from archie.derive.people import render_facts
    from archie.store.fence import set_fence
    note.body = set_fence(note.body, render_facts(note.meta, [{"text": "Test's son", "file": "sources/gmail/t1.json",
                                                               "chunk": "c0", "quote": "hi dad"}]))
    note.meta["facts_stale"] = True
    write_note(p, note)
    ctx.index.sync()
    enrich_people(ctx)
    after = read_note(p)
    assert "Test's son" not in get_fence(after.body)
    assert "facts_stale" not in after.meta
    assert "your child" in seen["system"] and "non-binary" in seen["system"]


def test_remember_stores_identity_and_marks_facts_stale(tmp_path):
    from archie.ask.intents.remember import apply_facts

    ctx = make_ctx(tmp_path)
    seed(ctx)
    said = "Childone is not my son. He is my child. He is non binary."
    apply_facts(ctx, said, [{"name": "Childone", "relationship": "child", "role": None, "pronouns": None,
                             "identity": "non-binary", "other_names": [], "statement": said}])
    meta = read_note(ctx.home / "people/childone_testerson.md").meta
    assert meta["identity"] == "non-binary" and meta["facts_stale"] is True


def test_words_to_avoid_reach_every_answer(tmp_path):
    ctx = make_ctx(tmp_path)
    p = seed(ctx)
    note = read_note(p)
    note.meta.update(pronouns="he/him", avoid=["boy", "son"])
    write_note(p, note)
    packet = Packet()
    packet.add("x.md", "c0", "Childone had a great day.")
    text = people_context(ctx, packet)
    assert "pronouns he/him" in text and "never call them: boy, son" in text


def test_remember_records_words_to_avoid(tmp_path):
    from archie.ask.intents.remember import apply_facts

    ctx = make_ctx(tmp_path)
    seed(ctx)
    said = "he/him are his pronouns, but he is non binary and doesn't like being called a boy"
    apply_facts(ctx, said, [{"name": "Childone", "relationship": None, "role": None, "pronouns": "he/him",
                             "identity": "non-binary", "avoid": ["boy", "son"], "other_names": [],
                             "statement": said}])
    assert read_note(ctx.home / "people/childone_testerson.md").meta["avoid"] == ["boy", "son"]
