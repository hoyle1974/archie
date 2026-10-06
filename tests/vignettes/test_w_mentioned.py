"""Vignette W (docs/VIGNETTES.md): someone I only mentioned."""

import json
from datetime import datetime, timezone

import yaml

from archie.store.files import read_note
from tests.support.fake_google import cal_event
from tests.vignettes.week import ME, Week, at, mail

LATER = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)  # every work meeting in the week is over


def workpersontwo_threads() -> dict:
    return {
        "t_koala": [mail("ko1", "t_koala", "Workpersontwo Birch (via Koalendar) <notifications@koalendar.com>", ME,
                         "New booking: Test Testerson & Workpersontwo Birch",
                         "Workpersontwo Birch booked a 30 minute video call with you for Wed, Sep 23.", at(22, 20, 11),
                         personal=False, headers={"List-Unsubscribe": "<mailto:u@koalendar.com>"})],
        "t_video": [mail("v1", "t_video", f"Test Testerson <{ME}>", f"Test Testerson <{ME}>",
                         "Updated video conference: Test Testerson & Workpersontwo Birch",
                         "Video link for the call with Workpersontwo: https://meet.example/abc", at(22, 21))],
        "t_workperson": [mail("kb1", "t_workperson", "Workperson Acorn <workperson@acorn.example>", f"Test Testerson <{ME}>",
                         "Intro", "Thanks for pinging Workpersontwo! She starts on the platform team soon.", at(1, 18))],
    }


def workpersontwo_events() -> list:
    return [cal_event("workpersontwo", "Test Testerson & Workpersontwo Birch", "2026-09-23T16:00:00Z", "2026-09-23T16:30:00Z",
                      description="Video call with Workpersontwo Birch."),
            cal_event("swim", "Goodspouse - Swimming", "2026-10-06T16:30:00Z", "2026-10-06T17:30:00Z")]


def week(tmp_path) -> Week:
    w = Week(tmp_path, more_threads=workpersontwo_threads(), more_events=workpersontwo_events())
    w.ctx.now = LATER
    return w


def _log(w):
    return [json.loads(x) for x in (w.ctx.home / "logs/usage.jsonl").read_text().splitlines()]


def test_W_prep_for_someone_only_mentioned_digs_and_offers_a_file(tmp_path):
    w = week(tmp_path)
    w.ask("I will meet with Workpersontwo next week")
    out = w.ask("Can you prep me for that meeting", sources=True)
    assert "no meetings" not in out.lower()
    assert "Workpersontwo" in out.split("\n")[0]  # the summary is about her
    assert "Test Testerson & Workpersontwo Birch" in out and "Intro" in out  # the Sep 23 call and Workperson's thread are cited
    assert "I looked further:" in out
    assert out.split("\n\nSources\n")[0].endswith(
        "I don't have a file on Workpersontwo Birch yet. The name is in 4 of your sources. Want me to start one?")
    entry = _log(w)[-1]
    assert entry["dead_end"] == "no file on anyone called Workpersontwo" and entry["dig"]["improved"]
    assert entry["offered"] == "Workpersontwo Birch"

    out = w.ask("yes")
    assert out.startswith("Started a file on Workpersontwo Birch")
    note = read_note(w.ctx.home / "people/workpersontwo_birch.md")
    assert note.meta["origin"] == "mentioned" and note.meta["status"] == "stub"
    assert "notifications@koalendar.com" not in note.meta["aliases"]

    out = w.ask("tell me about Workpersontwo")
    assert "didn't recognise" not in out and "I don't know anyone called" not in out
    assert "At a glance\n  Workpersontwo Birch\n" in out
    assert "(dossier)" not in out.split("Recent\n", 1)[1].split("\n\n")[0]  # her own file isn't news of her


def test_W_no_means_no_file_and_no_second_offer(tmp_path):
    w = week(tmp_path)
    w.ask("I will meet with Workpersontwo next week")
    w.ask("Can you prep me for that meeting")
    assert w.ask("no") == "OK, I won't keep a file on Workpersontwo Birch."
    assert yaml.safe_load((w.ctx.home / "state/people_declined.yaml").read_text()) == {"names": ["Workpersontwo Birch"]}
    w.ask("I will meet with Workpersontwo next week")
    out = w.ask("Can you prep me for that meeting")
    assert "Want me to start one?" not in out
    assert not (w.ctx.home / "people/workpersontwo_birch.md").exists()
