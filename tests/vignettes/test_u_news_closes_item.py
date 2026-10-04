"""Vignette U (docs/VIGNETTES.md): news that finishes an open item."""

import json

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import make_ctx, part, understood

SAID = "I was able to get my status earbuds to pair.  I will let them know it works now."


def model(system, user, shape, tier):
    if shape.name == "understand":
        assert "The user's open items:\n- waiting on HeadphonesRUs: Troubleshoot new earbud pairing issue" in user
        if "earbuds" in user.rsplit("Message:", 1)[-1]:
            return understood(part("instruct", action="loop_done", target="status earbuds"))
        return understood(part("tell", fact="other"))
    if shape.name == "loop_update":
        assert "1. HeadphonesRUs: Troubleshoot new earbud pairing issue" in user
        return {"loops": [1], "until": None, "reason": None, "one": True}
    raise AssertionError(shape.name)


def seeded(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(model))
    meta = {"loop_id": "l1", "kind": "waiting_on", "status": "open", "counterpart": "contact@headphonesrus.example",
            "counterpart_name": "HeadphonesRUs", "summary": "Troubleshoot new earbud pairing issue",
            "created_at": "2026-09-30T20:26:30+00:00", "due": None, "snoozed_until": None, "thread": "t1",
            "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    return ctx


def test_U_news_that_an_item_is_finished_marks_it_done(tmp_path):
    ctx = seeded(tmp_path)
    out = render(ask(ctx, SAID))
    assert out == "Marked done: HeadphonesRUs, troubleshoot new earbud pairing issue."
    assert [lp.meta["status"] for lp in load_loops(ctx.home)] == ["done"]
    told = (ctx.home / "journal/told.md").read_text()
    assert "I was able to get my status earbuds to pair. I will let them know it works now." in told
    assert "→ Marked done: HeadphonesRUs" in told
    entry = json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])
    assert "gaps" not in entry and entry["intent"] == "loop_done"


def test_U_other_news_is_still_only_saved(tmp_path):
    ctx = seeded(tmp_path)
    assert render(ask(ctx, "the pizza's picked up")) == "Saved. I don't use that for anything yet."
    assert [lp.meta["status"] for lp in load_loops(ctx.home)] == ["open"]
