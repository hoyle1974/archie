"""Vignette P (docs/VIGNETTES.md): "I can't do that yet"."""

import json

from archie.ask.intents.help import HELP
from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.loops import Loop, load_loops, save_loop
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from tests.support.fixtures import make_ctx, part, understood

PIZZA = "email Workpersonthree that the pizza's picked up"
WEEKDAYS = "only show work stuff on weekdays"
SNOOZE = "snooze the earbud one till Monday"


def model(system, user, shape, tier):
    if shape.name == "understand":
        said = user.rsplit("Message:", 1)[-1].strip()
        if said == PIZZA:
            return understood(part("tell", text="the pizza's picked up", fact="other"),
                              part("instruct", text="email Workpersonthree", action="send"))
        if said == WEEKDAYS:
            return understood(part("instruct", action="none", wanted="filter Today by day"))
        return understood(part("instruct", action="loop_snooze", target="the earbud one", until="2026-10-05"))
    if shape.name == "loop_update":  # picks the item only; never writes the confirmation
        return {"loops": [1], "until": None, "reason": None}
    raise AssertionError(f"unexpected model call: {shape.name}")


def gaps(ctx):
    return json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1]).get("gaps", [])


def test_P_archie_says_what_it_cannot_do_and_saves_the_wish(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    meta = {"loop_id": "l1", "kind": "waiting_on", "status": "open", "counterpart": "support@headphonesrus.example",
            "counterpart_name": "HeadphonesRUs", "summary": "Earbud pairing", "created_at": "2026-09-28T09:00:00+00:00",
            "due": None, "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    menu = HELP.strip().splitlines()[0]
    outs = []

    out = render(ask(ctx, PIZZA))
    outs.append(out)
    assert out == "I saved that the pizza's picked up. I can't send anything; I only read."
    assert gaps(ctx) == ["the pizza's picked up", "email Workpersonthree"]
    told = (ctx.home / "journal/told.md").read_text()
    assert '"the pizza\'s picked up" → saved only' in told and '"email Workpersonthree"' not in told

    out = render(ask(ctx, WEEKDAYS))
    outs.append(out)
    assert out == "I can't filter Today by day yet. I've saved that you want it."
    assert gaps(ctx) == [WEEKDAYS]
    assert f'"{WEEKDAYS}" → can\'t do this yet' in (ctx.home / "journal/told.md").read_text()
    assert [c["shape"].name for c in fb.calls] == ["understand", "understand"]

    out = render(ask(ctx, SNOOZE))
    outs.append(out)
    assert out == "Snoozed until Monday: HeadphonesRUs, earbud pairing."
    assert load_loops(ctx.home)[0].meta["snoozed_until"] == "2026-10-05"
    assert not any(menu in o for o in outs)  # a telling or instruction never gets the help menu
