"""Vignette O (docs/VIGNETTES.md): follow-ups."""

from datetime import timedelta

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from tests.support.fixtures import NOW, make_ctx, question, understood

DOSSIER = ("---\nname: HeadphonesRUs\n---\n## My notes\n"
           "You wrote to HeadphonesRUs on Oct 2: one earbud pairs and the other stays red.\n"
           "HeadphonesRUs replied Oct 3, offering a replacement right earbud for $49.\n")
FOLLOW_UP = "Do you see the message I sent HeadphonesRUs about the earbud pairing?"


def model(system, user, shape, tier):
    if shape.name == "understand":
        msg = user.rsplit("Message:", 1)[-1].strip()
        if msg.startswith("do you see"):
            return understood(question("search", resolved=FOLLOW_UP, people=["HeadphonesRUs"], topic="earbud pairing"))
        return understood(question("search", topic="HeadphonesRUs earbud"))
    return {"summary": [{"text": "HeadphonesRUs offered a replacement right earbud.",
                         "citations": [{"ref": 1, "quote": "offering a replacement right earbud for $49"}]}],
            "sections": []}


def test_O_follow_ups(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    atomic_write(ctx.home / "people/status_audio.md", DOSSIER)
    ctx.index.sync()

    first = render(ask(ctx, "did Status reply about my earbud?"))
    assert "[1]" in first

    ctx.now = NOW + timedelta(minutes=2)
    ask(ctx, "do you see the message I sent them?")
    seen = fb.calls[-2]["user"]  # the understanding call for the follow-up
    assert "You: did Status reply about my earbud?" in seen and "Archie: HeadphonesRUs offered" in seen
    assert f"Question (answer it from the sources above): {FOLLOW_UP}" in fb.calls[-1]["user"]  # the answer was written for the resolved question

    ctx.now = NOW + timedelta(minutes=3)
    calls = len(fb.calls)
    shown = render(ask(ctx, "show 1"))
    assert len(fb.calls) == calls  # no model call
    assert shown.startswith("[1] ") and "offering a replacement right earbud for $49" in shown
    assert shown.splitlines()[-1] == "people/status_audio.md"

    ctx.now = NOW + timedelta(minutes=4)
    again = render(ask(ctx, "really?"))
    assert again.startswith("I checked again.")
    assert "This is different" not in again
    assert f"Question (answer it from the sources above): {FOLLOW_UP}" in fb.calls[-1]["user"]  # the same question, asked again

    ctx.now = NOW + timedelta(minutes=45)
    ask(ctx, "do you see the message I sent them?")
    assert "Recent conversation" not in fb.calls[-2]["user"]  # after a quiet half hour, a fresh start


def test_O_really_with_nothing_recent_is_an_ordinary_message(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    render(ask(ctx, "really?"))
    assert fb.calls[0]["shape"].name == "understand"
    ctx.now = NOW + timedelta(minutes=1)
    render(ask(ctx, "really?"))  # the last exchange was itself "really?": no endless re-asking
    assert fb.calls[-1]["shape"].name in ("understand", "answer")
