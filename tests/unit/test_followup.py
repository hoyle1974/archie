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


def test_context_keeps_lines_and_drops_front_matter_and_fences():
    from archie.ask.followup import _around

    chunk = ("---\nentity_id: workpersontwo\n---\n## My notes\n\n<!-- archie:auto -->\n"
             "- I haven't scheduled it yet. _(you said, Oct 5)_\n- I will meet with Workpersontwo\n  next week\n"
             "<!-- /archie:auto -->\n")
    assert _around(chunk, "I will meet with Workpersontwo next week") == \
        "## My notes\n\n- I haven't scheduled it yet. _(you said, Oct 5)_\n- I will meet with Workpersontwo\n  next week"


def test_context_cuts_at_line_breaks_with_an_ellipsis_line():
    from archie.ask.followup import _around

    chunk = "\n".join(f"- line {i} " + "x" * 30 for i in range(20))
    around = _around(chunk, "line 10", width=60)
    assert around.startswith("…\n\n- line ") and around.endswith("\n\n…") and "- line 10 " in around


def test_show_marks_markdown_sources_as_markdown(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    chunks = {"people/a.md": "## A\n- alpha beta gamma\n", "sources/gmail/t.json": "Subject: Hi\ndelta epsilon\nzeta"}
    monkeypatch.setattr(ctx.index, "chunk_text", lambda path, chunk: chunks[path])
    md = show(ctx, LAST, 1)
    assert md.markdown == "## A\n- alpha beta gamma" and md.markdown in render(md)
    last = {"citations": [{"n": 1, "file": "sources/gmail/t.json", "chunk": "c0", "label": "B", "quote": "delta epsilon"}]}
    plain = show(ctx, last, 1)
    assert plain.markdown is None and "Subject: Hi\ndelta epsilon\nzeta" in render(plain)
