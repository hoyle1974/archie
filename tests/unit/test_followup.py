from archie.ask.answer import Answer
from archie.ask.followup import citation_number, is_recheck, recheck, show
from archie.ask.render import render
from tests.support.fixtures import make_ctx

LAST = {"said": "q", "resolved": None, "summary": "s",
        "citations": [{"n": 1, "file": "people/a.md", "chunk": "c0", "label": "A (dossier)", "quote": "alpha beta gamma"},
                      {"n": 2, "file": "people/b.md", "chunk": "c0", "label": "B (dossier)", "quote": "delta epsilon"}]}


def test_citation_number():
    assert [citation_number(t) for t in ("show 1", "Show [2]", "open source 3", "show me citation 4.", "show me")] == \
        [1, 2, 3, 4, None]


def test_is_recheck():
    assert all(is_recheck(t) for t in ("really?", "Really", "are you sure?", "is that right?", "double-check that"))
    assert not is_recheck("really, who is Priya?")


def test_show_missing_citation_says_what_exists(tmp_path):
    ctx = make_ctx(tmp_path)
    assert render(show(ctx, LAST, 3)) == "The last answer has citations 1–2."
    assert render(show(ctx, {"citations": []}, 1)) == "There's no recent answer with sources to show."
    assert render(show(ctx, None, 1)) == "There's no recent answer with sources to show."


def test_show_leads_with_the_label_and_ends_with_the_path(tmp_path):
    ctx = make_ctx(tmp_path)
    lines = render(show(ctx, LAST, 2)).splitlines()
    assert lines[0] == "[2] B (dossier)" and lines[1] == "“delta epsilon”" and lines[-1] == "people/b.md"


def test_recheck_says_when_the_answer_changed():
    same = recheck(LAST, Answer(plain="x"), [{"file": "people/a.md"}])
    assert render(same) == "I checked again.\nx"
    changed = recheck(LAST, Answer(nothing_found=True), [])
    assert render(changed).startswith("I checked again. This is different from my earlier answer.\n")


def test_context_is_empty_when_the_quote_is_not_in_the_chunk():
    from archie.ask.followup import _around

    assert _around("Some unrelated chunk text.", "a quote that is elsewhere") == ""
