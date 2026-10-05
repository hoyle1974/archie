import time

import pytest

from archie.derive.titles import Title, role_line, title_from_signature

NAMES = {"workperson acorn", "workperson"}


@pytest.fixture(autouse=True)
def pacific(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_title_skips_name_phone_url_and_company():
    assert title_from_signature("Workperson Acorn\nDirector of Engineering\n781-526-7220", NAMES, "overwatchdata.io") \
        == "Director of Engineering"
    assert title_from_signature("Workperson Acorn\nOverwatch Data\nVP of Engineering", NAMES, "overwatchdata.io") \
        == "VP of Engineering"


def test_no_title_gives_none():
    for sig in ("Workperson Acorn\n781-526-7220", "Sent from my iPhone", "Thanks!", "Workperson\nhttps://ow.example",
                "Workperson Acorn\nkeith@ow.example"):
        assert title_from_signature(sig, NAMES, "ow.example") is None, sig


def test_sent_from_my_phone_is_not_a_title():
    assert title_from_signature("Sent from my iPhone", set(), None) is None


def test_role_line_shows_every_title_newest_first():
    one = [Title("Director of Engineering", "2026-09-22T20:16:16+00:00", "p", "s0")]
    two = one + [Title("VP of Engineering", "2026-09-18T02:13:48+00:00", "q", "s0")]
    assert role_line(one) == "Role: Director of Engineering (signed Sep 22)"
    assert role_line(two) == "Role: signs as Director of Engineering (Sep 22) and VP of Engineering (Sep 17)"
    assert role_line([]) is None


def test_lines_that_are_not_titles_give_none():
    for line in ("Overwatch Data, Inc.", "Acme Corporation", "Seattle, WA", "Be kind whenever possible",
                 "Get Outlook for iOS", "Sent with Proton Mail secure email.", "Best regards,", "K. Acorn",
                 "CONFIDENTIALITY NOTICE: This message is for the named person only",
                 "Please consider the environment before printing", "Original Message"):
        assert title_from_signature(f"Workperson Acorn\n{line}", NAMES, "overwatchdata.io") is None, line


def test_titles_in_many_shapes_are_found():
    for line in ("Product Manager, Auth", "Senior Software Engineer", "Co-founder & CEO", "Head of People",
                 "Principal, Lincoln Elementary", "Talent Partner", "Professor of Chemistry"):
        assert title_from_signature(f"Workperson Acorn\n{line}", NAMES, "overwatchdata.io") == line, line
