"""Vignette Q (docs/VIGNETTES.md): "Which one did you mean?"."""

from datetime import timedelta

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import make_ctx, part, question, understood

ASKED = "Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?"


def model(system, user, shape, tier):
    if shape.name == "understand":
        said = user.rsplit("Message:", 1)[-1].strip()
        if said == "she's done with it":
            return understood(part("instruct", text=said, action="loop_done"))
        return understood(question("search"))
    if shape.name == "loop_update":  # "she" and "it" fit both items
        return {"loops": [1, 2], "until": None, "reason": None, "one": True}
    return {"summary": [], "sections": []}


def seeded(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(model))
    for i, (who, email, what, created) in enumerate([
            ("Workpersonthree", "workpersonthree@x.example", "Pizza instructions", "2026-09-28T09:00:00+00:00"),
            ("Workpersonfour", "workpersonfour@school.example", "IEP form", "2026-09-30T09:00:00+00:00")], 1):
        meta = {"loop_id": f"l{i}", "kind": "asked_of_me", "status": "open", "counterpart": email,
                "counterpart_name": who, "summary": what, "created_at": created, "due": None, "snoozed_until": None,
                "thread": f"t{i}", "addressed": "to", "sources": [], "closed_by": None}
        save_loop(ctx.home, Loop(f"l{i}", f"loops/2026/l{i}.md", Note(meta=meta, body="")))
    return ctx


def statuses(ctx):
    return {lp.meta["counterpart_name"]: lp.meta["status"] for lp in load_loops(ctx.home)}


def test_Q_archie_asks_which_one_and_applies_the_short_reply(tmp_path):
    ctx = seeded(tmp_path)
    assert render(ask(ctx, "she's done with it")) == ASKED
    assert statuses(ctx) == {"Workpersonthree": "open", "Workpersonfour": "open"}

    calls = len(ctx.backend.calls)
    assert render(ask(ctx, "Workpersonthree's")) == "Marked done: Workpersonthree, pizza instructions."
    assert len(ctx.backend.calls) == calls  # matched by code
    assert statuses(ctx) == {"Workpersonthree": "done", "Workpersonfour": "open"}


def test_Q_no_answer_within_thirty_minutes_changes_nothing(tmp_path):
    ctx = seeded(tmp_path)
    assert render(ask(ctx, "she's done with it")) == ASKED
    ctx.now += timedelta(minutes=31)
    ask(ctx, "Workpersonthree's")
    assert statuses(ctx) == {"Workpersonthree": "open", "Workpersonfour": "open"}
