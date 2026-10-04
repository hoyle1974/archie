import json

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.ask.tell import TOLD, save_told, tell
from archie.config import load_config
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, atomic_write, write_note
from tests.support.fixtures import by_schema, make_ctx, part, understood
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"


def seeded(tmp_path, backend=None, name=""):
    ctx = make_ctx(tmp_path, backend or FakeBackend([]))
    derive_people(ctx, [write_thread(ctx.home, "t1", [msg("m1", SPAM, name, [addr("test@acme.example")],
                                                         "2026-09-30T09:00:00+00:00", "Yeti offer", to_me=True)])])
    return ctx


def told(ctx):
    return (ctx.home / TOLD).read_text()


def test_told_lines_append_cleanly_to_a_file_the_user_edited(tmp_path):
    ctx = make_ctx(tmp_path)
    atomic_write(ctx.home / TOLD, "# My list\n- something I wrote")  # no trailing newline
    save_told(ctx, "Sam is   my\nneighbor.", "saved only")
    assert told(ctx) == '# My list\n- something I wrote\n- 2026-10-01 · "Sam is my neighbor." → saved only\n'


def test_ignore_by_address_replies_from_code_and_saves_the_words(tmp_path):
    ctx = seeded(tmp_path, name="Goodcompany")
    out = render(tell(ctx, "ignore", f"{SPAM} is spam, ignore it"))
    assert out == f"Got it. I'll ignore Goodcompany ({SPAM}) from now on.\nSay \"stop ignoring Goodcompany\" to undo."
    assert f'"{SPAM} is spam, ignore it" → ignoring {SPAM}' in told(ctx)
    assert ctx.backend.calls == []  # the user's words are taken as said, never checked


def test_stop_ignoring_by_name_and_saying_so_twice(tmp_path):
    ctx = seeded(tmp_path, name="Goodcompany")
    tell(ctx, "ignore", f"ignore {SPAM}")
    undo = "stop ignoring Goodcompany"
    assert render(tell(ctx, "unignore", undo, about="Goodcompany")) == f"OK, I'm no longer ignoring Goodcompany ({SPAM})."
    assert render(tell(ctx, "unignore", undo, about="Goodcompany")) == f"I wasn't ignoring Goodcompany ({SPAM})."
    assert f'"{undo}" → no longer ignoring {SPAM}' in told(ctx)


def test_an_unknown_sender_ignores_nobody(tmp_path):
    ctx = seeded(tmp_path)
    assert render(tell(ctx, "ignore", "ignore the pizza place", about="the pizza place")) == \
        "I couldn't tell which sender you mean, so I haven't ignored anyone. Try their email address."
    assert told(ctx).endswith("→ saved only\n") and load_config(ctx.home)["ignore"] == []


def test_a_name_two_people_share_asks_which(tmp_path):
    ctx = make_ctx(tmp_path)
    for eid, email in (("alex_rivera", "alex@acme.example"), ("alex_kim", "alex.k@other.example")):
        write_note(ctx.home / f"people/{eid}.md",
                   Note(meta={"entity_id": eid, "name": eid.replace("_", " ").title(), "aliases": [email]}, body=""))
    assert render(tell(ctx, "ignore", "ignore Alex", about="Alex")) == \
        "Which one: Alex Kim or Alex Rivera? Say their email address to be sure."
    assert load_config(ctx.home)["ignore"] == []


def test_never_ignores_your_own_address(tmp_path):
    ctx = seeded(tmp_path)
    assert render(tell(ctx, "ignore", "ignore test@acme.example")) == "I won't ignore your own address."
    assert load_config(ctx.home)["ignore"] == []


def test_other_tellings_are_saved_and_logged_as_gaps(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("tell", fact="other")))))
    assert render(ask(ctx, "I prefer mornings for meetings")) == "Saved. I don't use that for anything yet."
    assert '"I prefer mornings for meetings" → saved only' in told(ctx)
    log = json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])
    assert log["gaps"] == ["I prefer mornings for meetings"]


def test_an_answer_to_who_is_can_ignore_the_sender(tmp_path):
    ctx = seeded(tmp_path, FakeBackend(by_schema(understand=understood(part("answer", question=1, fact="ignore")))))
    audit(ctx)
    out = render(ask(ctx, "it's spam, ignore it"))
    assert out.startswith(f"Got it. I'll ignore {SPAM} from now on.")
    assert open_questions(ctx.home) == []
    assert f'"it\'s spam, ignore it" → ignoring {SPAM}' in told(ctx)


def test_an_instruction_to_ignore_goes_to_the_same_code(tmp_path):
    reply = understood(part("instruct", action="ignore", target=SPAM))
    ctx = seeded(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, f"ignore {SPAM}")).startswith(f"Got it. I'll ignore {SPAM} from now on.")


def test_yes_no_answers_are_saved_with_what_they_did(tmp_path):
    from archie.derive.loops import Loop, save_loop

    ctx = make_ctx(tmp_path)  # a plain "yes" takes the shortcut: no model call
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "maybe_done", "counterpart": "sam",
            "counterpart_name": "Sam", "summary": "Do l1", "created_at": "2026-09-01T00:00:00+00:00", "due": None,
            "snoozed_until": None, "thread": "t", "addressed": "to", "sources": [],
            "closed_by": {"file": "f", "chunk": "c0", "quote": "q"}}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    audit(ctx)
    assert render(ask(ctx, "yes")) == "Marked done: Do l1."
    assert '"yes" → Marked done: Do l1.' in told(ctx)
