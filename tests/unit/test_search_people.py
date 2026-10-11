"""A question about a person and a topic searches the topic among things that person was
part of (review 2026-10-04: "Tell me about Goodspouse and CPS" searched "CPS Goodspouse" as words,
got Goodspouse's swimming events, and missed her email about the CPS report)."""

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx, question, understood
from tests.support.raw import addr, msg, write_thread

ME = "test@acme.example"
GOODSPOUSE = "goodspouse@x.example"
LONG = " ".join(["Childone had a hard year with a lot of change and many meetings."] * 40)


def seed(ctx):
    paths = [write_thread(ctx.home, "t1", [msg("m1", GOODSPOUSE, "Goodspouse Testerson", [addr(ME)], "2026-09-28T10:00:00+00:00",
                                               f"{LONG} That man filed a false CPS report about me. {LONG}",
                                               subject="Student Support Team Meeting", to_me=True)])]
    paths += [write_thread(ctx.home, f"s{i}", [msg(f"s{i}", ME, "Test", [addr("pool@swim.example")],
                                                   f"2026-10-0{i}T10:00:00+00:00", "Goodspouse swimming Goodspouse",
                                                   subject="Goodspouse - Swimming", from_me=True)])
              for i in range(1, 10)]
    derive_people(ctx, paths)
    ctx.index.sync()


def test_a_person_and_a_topic_finds_the_topic_in_that_persons_mail(tmp_path):
    seen = []

    def answer(system, user, shape, tier):
        seen.append(user)
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(question("search", topic="CPS", people=["Goodspouse"])), answer=answer)))
    seed(ctx)
    render(ask(ctx, "Tell me about Goodspouse and CPS"))
    first = seen[0].split("\n[2]")[0]
    assert "false CPS report" in first  # her email leads the packet, ahead of the swimming notes


def test_sources_come_ranked_with_a_match_score_within_the_limits(tmp_path):
    import re

    seen = []

    def answer(system, user, shape, tier):
        seen.append(user)
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        understand=understood(question("search", topic="swimming")), answer=answer)))
    seed(ctx)
    write_thread(ctx.home, "huge", [msg("h1", "pool@swim.example", "Pool", [addr(ME)], "2026-10-02T10:00:00+00:00",
                                        "swimming " * 3000, subject="Swimming schedule", to_me=True)])
    ctx.index.sync()
    ctx.config["ask"] = {"max_sources": 5, "max_source_chars": 2000}
    ask(ctx, "when is swimming?")
    scores = [float(m) for m in re.findall(r'match="(\d\.\d\d)"', seen[0])]
    assert 1 < len(scores) <= 5 and scores[0] == 1.0 and scores == sorted(scores, reverse=True)
    assert "swimming swimming swimming swimming" not in seen[0]  # too big to fit: skipped, not the rest


def test_a_repeating_event_is_one_source_with_its_other_dates():
    from archie.ask.intents.search import packet_from_hits
    from archie.index.search import Hit

    hits = [Hit(f"sources/calendar/e{i}.json", "c0", "Event: Childone pick up\nWhen: Wed", "calendar",
                f"2026-10-{7 + 7 * i:02d}T21:15:00+00:00", 0, 0, label=f"Event: Childone pick up (Wed Oct {7 + 7 * i})",
                score=1.0 - i / 10) for i in range(3)]
    p = packet_from_hits(hits)
    assert len(p.items) == 1 and "Repeats: also" in p.items[0].note and "Oct 21" in p.items[0].note
