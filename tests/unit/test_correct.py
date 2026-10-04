from datetime import datetime, timezone

import yaml

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.meetings import load_meetings
from archie.derive.people import PeopleDirectory
from archie.llm.backend import FakeBackend
from archie.store.files import read_note
from tests.support.fixtures import by_schema, make_ctx, part, understood
from tests.unit.test_briefings import seed

NOW = datetime(2026, 10, 1, 20, 45, tzinfo=timezone.utc)
ROUTE = understood(part("instruct", action="meeting_type"))


def fix(**kw):
    base = {"kind": "meeting_type", "meeting": None, "meeting_type": None, "alias": None, "person": None, "role": None}
    base.update(kw)
    return base


def test_meeting_type_override_applies_to_series(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE, correct=fix(meeting="design review",
                                                                            meeting_type="one_on_one"))), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "the design review is a 1:1"))
    assert "1:1" in out
    data = yaml.safe_load((ctx.home / "config/meeting_types.yaml").read_text())
    assert data["titles"]["Design Review: Auth Redesign"] == "one_on_one"
    m = next(x for x in load_meetings(ctx.home) if x.meta["title"].startswith("Design Review"))
    assert m.meta["type"] == "one_on_one"


def test_alias_is_added_to_the_named_person(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE, correct=fix(kind="same_person", alias="Al R.",
                                                                            person="Alex Rivera"))), now=NOW)
    seed(ctx)
    out = render(ask(ctx, "Al R. is Alex Rivera"))
    assert "Al R." in read_note(ctx.home / "people/alex_rivera.md").meta["aliases"]
    assert PeopleDirectory.load(ctx.home).find("Al R.") == ["alex_rivera"]
    assert "Got it" in out


def test_role_is_set(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE, correct=fix(kind="role", person="Priya",
                                                                            role="PM for auth"))), now=NOW)
    seed(ctx)
    render(ask(ctx, "Priya is the PM for auth"))
    assert read_note(ctx.home / "people/priya_sharma.md").meta["role"] == "PM for auth"


def test_unknown_person_is_reported(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE, correct=fix(kind="role", person="Zed", role="x"))),
                   now=NOW)
    seed(ctx)
    assert "don't know" in render(ask(ctx, "Zed is x"))
