import yaml

from archie.config import load_config
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.ignore import addresses_for, describe, ignored, on_list, set_ignored
from archie.derive.loops import Loop, derive_loops, load_loops, save_loop
from archie.derive.people import PeopleDirectory, derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, read_note, write_note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"


def seed(ctx, name=""):
    """A sender with a dossier and one open item from them."""
    path = write_thread(ctx.home, "t1", [msg("m1", SPAM, name, [addr("test@acme.example")],
                                            "2026-09-30T09:00:00+00:00", "Can you check our Yeti offer?",
                                            to_me=True)])
    derive_people(ctx, [path])
    eid = PeopleDirectory.load(ctx.home).by_email(SPAM)
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "open", "counterpart": eid,
            "counterpart_name": name or SPAM, "summary": "Check the offer", "created_at": "2026-09-30T09:00:00+00:00",
            "due": None, "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    return eid


def test_on_list_matches_addresses_and_whole_domains():
    assert on_list("Ken@Acme.example", ["ken@acme.example"])
    assert on_list("x@spam.example", ["@spam.example"]) and on_list("x@SPAM.example", ["@Spam.Example"])
    assert not on_list("x@notspam.example", ["@spam.example"])
    assert not on_list("", ["@spam.example"]) and not on_list("ken@acme.example", [])


def test_ignoring_writes_config_flags_the_dossier_and_dismisses_open_items(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    assert set_ignored(ctx, [SPAM], on=True) == 1
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]
    assert SPAM in ignored(ctx.config) and load_config(ctx.home)["ignore"] == [SPAM]
    assert read_note(ctx.home / f"people/{eid}.md").meta["ignored"] is True
    [lp] = load_loops(ctx.home)
    assert lp.meta["status"] == "dismissed" and lp.meta["dismissed_reason"] == "ignored"
    assert "you told Archie to ignore this sender" in lp.note.body
    assert set_ignored(ctx, [SPAM], on=True) == 0  # already ignored: no duplicate entry
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]


def test_ignored_senders_get_no_questions_and_open_ones_resolve(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    audit(ctx)
    assert [q["kind"] for q in open_questions(ctx.home)] == ["who_is"]
    set_ignored(ctx, ["@sxziiqsov.us"], on=True)
    audit(ctx)
    assert open_questions(ctx.home) == []


def test_new_mail_from_an_ignored_sender_makes_no_items_and_no_model_call(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    set_ignored(ctx, ["@sxziiqsov.us"], on=True)
    path = write_thread(ctx.home, "t2", [msg("m9", SPAM, "", [addr("test@acme.example")],
                                           "2026-10-01T09:00:00+00:00", "Can you reply about the offer?", to_me=True)])
    derive_loops(ctx, [path])
    assert load_loops(ctx.home) == [] and ctx.backend.calls == []


def test_unignoring_removes_it_from_both_lists(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    ctx.home.config_file.write_text(yaml.safe_dump({"loops": {"mute": [SPAM, "other@x.example"]}}))
    ctx.config["loops"]["mute"] = [SPAM, "other@x.example"]
    set_ignored(ctx, [SPAM], on=True)
    assert set_ignored(ctx, [SPAM], on=False) == 0
    cfg = yaml.safe_load(ctx.home.config_file.read_text())
    assert cfg["ignore"] == [] and cfg["loops"]["mute"] == ["other@x.example"]
    assert SPAM not in ignored(ctx.config)
    assert "ignored" not in read_note(ctx.home / f"people/{eid}.md").meta


def test_addresses_come_from_the_words_or_from_one_matching_person(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, name="Goodcompany")
    d = PeopleDirectory.load(ctx.home)
    assert addresses_for(d, None, f"{SPAM} is spam") == ([SPAM], [])
    assert addresses_for(d, None, "ignore everything from @sxziiqsov.us") == (["@sxziiqsov.us"], [])
    assert addresses_for(d, "Goodcompany", "ignore Goodcompany") == ([SPAM], [])
    assert addresses_for(d, "the pizza place", "ignore the pizza place") == ([], [])
    assert addresses_for(d, None, "ignore it") == ([], [])


def test_a_name_two_people_share_gives_both_names_and_no_addresses(tmp_path):
    ctx = make_ctx(tmp_path)
    for eid, email in (("alex_rivera", "alex@acme.example"), ("alex_kim", "alex.k@other.example")):
        write_note(ctx.home / f"people/{eid}.md",
                   Note(meta={"entity_id": eid, "name": eid.replace("_", " ").title(), "aliases": [email]}, body=""))
    assert addresses_for(PeopleDirectory.load(ctx.home), "Alex", "ignore Alex") == ([], ["Alex Kim", "Alex Rivera"])


def test_describe_uses_the_name_when_there_is_one(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, name="Goodcompany")
    d = PeopleDirectory.load(ctx.home)
    assert describe(d, [SPAM]) == (f"Goodcompany ({SPAM})", "Goodcompany")
    assert describe(d, ["@sxziiqsov.us"]) == ("@sxziiqsov.us", "@sxziiqsov.us")
    assert describe(PeopleDirectory(), [SPAM]) == (SPAM, SPAM)


def test_answers_leave_out_ignored_senders_unless_the_question_names_them(tmp_path):
    from archie.ask.pipeline import ask
    from tests.support.fixtures import question, understood

    seen = []

    def model(system, user, shape, tier):
        if shape.name == "understand":
            return understood(question("search", topic="Yeti offer"))
        seen.append(user)
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(model))
    seed(ctx, name="Goodcompany")
    write_thread(ctx.home, "t3", [msg("m3", "ken@acme.example", "Ken", [addr("test@acme.example")],
                                      "2026-09-30T10:00:00+00:00", "Ken says the Yeti offer is a scam.", to_me=True)])
    ctx.index.sync()
    set_ignored(ctx, [SPAM], on=True)
    ask(ctx, "anything about the Yeti offer?")
    assert "Ken says" in seen[-1] and "Can you check our Yeti offer" not in seen[-1]
    for named in (f"what did {SPAM} say about the Yeti offer?", "what did Goodcompany say about the Yeti offer?",
                  "anything from sxziiqsov.us about the Yeti offer?"):
        ask(ctx, named)
        assert "Can you check our Yeti offer" in seen[-1], named
