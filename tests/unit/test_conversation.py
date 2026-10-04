from datetime import datetime, timedelta, timezone

from archie.ask import conversation
from archie.ask.answer import Answer, Section
from archie.ask.render import citations_of, render
from archie.llm.verify import Citation, Claim
from archie.store.home import init_home

T0 = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)


def entry(said, at):
    return {"ts": at.isoformat(), "said": said, "resolved": None, "summary": "", "citations": []}


def test_recent_is_the_last_three_oldest_first(tmp_path):
    home = init_home(tmp_path / "h")
    for i in range(5):
        conversation.append(home, entry(f"q{i}", T0 + timedelta(minutes=i)))
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=6))] == ["q2", "q3", "q4"]


def test_a_quiet_half_hour_starts_fresh(tmp_path):
    home = init_home(tmp_path / "h")
    conversation.append(home, entry("old topic", T0))
    conversation.append(home, entry("new topic", T0 + timedelta(minutes=45)))
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=46))] == ["new topic"]
    assert conversation.recent(home, T0 + timedelta(minutes=80)) == []


def test_the_file_keeps_the_last_200(tmp_path):
    home = init_home(tmp_path / "h")
    for i in range(205):
        conversation.append(home, entry(f"q{i}", T0))
    saved = conversation.load(home)
    assert len(saved) == 200 and saved[0]["said"] == "q5"


def test_a_damaged_line_is_skipped(tmp_path):
    home = init_home(tmp_path / "h")
    conversation.append(home, entry("fine", T0))
    with (home / conversation.FILE).open("a") as fh:
        fh.write('{"ts": "2026-10-03T18:01\n')
    assert [e["said"] for e in conversation.load(home)] == ["fine"]
    assert [e["said"] for e in conversation.recent(home, T0 + timedelta(minutes=2))] == ["fine"]


def test_citations_are_numbered_like_the_rendered_answer():
    a = Citation(1, "people/a.md", "c0", "alpha quote here", "A (dossier)")
    b = Citation(2, "sources/gmail/t.json", "c3", "beta quote here", "Email, Oct 2")
    ans = Answer(summary=[Claim("First.", [b])], sections=[Section("More", [Claim("Second.", [a, b])])])
    assert "First. [1]" in render(ans) and "Second. [2][1]" in render(ans)
    assert citations_of(ans) == [
        {"n": 1, "file": "sources/gmail/t.json", "chunk": "c3", "label": "Email, Oct 2", "quote": "beta quote here"},
        {"n": 2, "file": "people/a.md", "chunk": "c0", "label": "A (dossier)", "quote": "alpha quote here"}]
    assert citations_of(Answer(plain="help text")) == []
