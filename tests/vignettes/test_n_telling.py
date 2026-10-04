"""Vignette N (docs/VIGNETTES.md): telling Archie something."""

import yaml

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.loops import Loop, derive_loops, load_loops, save_loop
from archie.derive.people import PeopleDirectory, derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from archie.tui.feed import build_feed
from tests.support.fixtures import make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"
SAID = f"{SPAM} is spam, ignore it"


def model(system, user, shape, tier):
    if shape.name == "understand":
        said = user.rsplit("Message:", 1)[-1].strip()
        if said == SAID:
            return understood(part("answer", question=1, fact="ignore"))
        if said.startswith("stop ignoring"):
            return understood(part("tell", fact="unignore", about=SPAM))
        return understood(question("search", topic="Yeti cooler"))
    return {"summary": [], "sections": []}


def seed(ctx):
    path = write_thread(ctx.home, "t1", [msg("m1", SPAM, "", [addr("test@acme.example")], "2026-09-30T09:00:00+00:00",
                                            "Can you claim your Yeti cooler reward?", to_me=True)])
    derive_people(ctx, [path])
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "open",
            "counterpart": PeopleDirectory.load(ctx.home).by_email(SPAM), "counterpart_name": SPAM,
            "summary": "Claim the reward", "created_at": "2026-09-30T09:00:00+00:00", "due": None,
            "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    ctx.index.sync()


def test_N_telling_archie_to_ignore_a_sender(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    audit(ctx)
    assert [q["text"].split("?")[0] for q in open_questions(ctx.home)] == [f"Who is {SPAM}"]

    out = render(ask(ctx, SAID))
    assert out == (f"Got it. I'll ignore {SPAM} from now on.\nSay \"stop ignoring {SPAM}\" to undo.\n"
                   "I also dismissed 1 open item from them.")
    assert [c["shape"].name for c in fb.calls] == ["understand"]  # the user's words are never checked
    assert f'"{SAID}" → ignoring {SPAM}' in (ctx.home / "journal/told.md").read_text()
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]

    audit(ctx)  # the next sync's checks ask nothing about the sender
    assert open_questions(ctx.home) == []
    feed = build_feed(ctx)
    assert SPAM not in feed and "Claim the reward" not in feed

    later = write_thread(ctx.home, "t2", [msg("m2", SPAM, "", [addr("test@acme.example")],
                                            "2026-10-01T08:00:00+00:00", "Can you confirm your Yeti cooler address?",
                                            to_me=True)])
    before = len(fb.calls)
    derive_loops(ctx, [later])
    assert len(fb.calls) == before and [lp.meta["status"] for lp in load_loops(ctx.home)] == ["dismissed"]

    ctx.index.sync()
    before = len(fb.calls)
    ask(ctx, "any Yeti cooler deals?")
    assert not any("Yeti cooler reward" in c["user"] or "Yeti cooler address" in c["user"]
                   for c in fb.calls[before:] if c["shape"].name != "understand")
    ask(ctx, f"what did {SPAM} send about the Yeti cooler?")
    assert "Yeti cooler" in fb.calls[-1]["user"] and fb.calls[-1]["shape"].name != "understand"

    assert render(ask(ctx, f"stop ignoring {SPAM}")) == f"OK, I'm no longer ignoring {SPAM}."
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == []


def test_N_a_description_and_full_name_land_in_the_persons_file(tmp_path):
    from archie.store.files import read_note

    said = "Acorn's full name is Acorn Testerson.  Acorn is full of energy and is 3 and a half years old."

    def people(system, user, shape, tier):
        if shape.name == "understand":
            return understood(part("tell", fact="person", about="Acorn"))
        return {"people": [{"name": "Acorn", "relationship": None, "role": None, "pronouns": None,
                            "identity": None, "avoid": [], "full_name": "Acorn Testerson",
                            "other_names": [], "statement": said}]}

    ctx = make_ctx(tmp_path, FakeBackend(people))
    assert render(ask(ctx, said)) == "Got it. I'll remember:\n  • Acorn (Acorn Testerson), new"
    acorn = read_note(ctx.home / "people/acorn.md")
    assert acorn.meta["name"] == "Acorn" and acorn.meta["full_name"] == "Acorn Testerson"
    assert "Acorn is full of energy and is 3 and a half years old." in acorn.body
