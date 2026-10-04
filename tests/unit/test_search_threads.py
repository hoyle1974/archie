"""Questions about a conversation lead with its newest message (review 2026-10-04: "do you
see the message I sent them?" showed 2023 messages and missed the user's Oct 2 one)."""

from archie.ask.pipeline import ask
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx, question, understood
from tests.support.raw import addr, msg, write_thread

ME = "test@acme.example"
STATUS = "contact@headphonesrus.example"


def seed(ctx):
    old = [msg(f"o{i}", STATUS, "HeadphonesRUs", [addr(ME)], f"2023-07-1{i}T10:00:00+00:00",
               "Status earbud app: uninstall the app, re-download it and reconnect your earbud.", to_me=True)
           for i in range(4)]
    write_thread(ctx.home, "old", old)
    write_thread(ctx.home, "new", [
        msg("n0", STATUS, "HeadphonesRUs", [addr(ME)], "2026-09-29T10:00:00+00:00", "Your replacement earbud shipped.",
            to_me=True),
        msg("n1", ME, "Test", [addr(STATUS)], "2026-09-30T20:00:00+00:00",
            "I received the new one and am trying to pair it. One stays red.", from_me=True),
        msg("n2", STATUS, "HeadphonesRUs", [addr(ME)], "2026-10-01T04:47:00+00:00",
            "Please pair this earbud with your current case using this setup guide.", to_me=True),
    ])
    ctx.index.sync()


def run(tmp_path, said):
    seen = {}

    def answer(system, user, shape, tier):
        seen["system"], seen["user"] = system, user
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("search", topic="Status earbud")),
                                                   answer=answer)))
    seed(ctx)
    ask(ctx, said)
    return seen


def test_a_conversation_question_shows_the_newest_messages_first(tmp_path):
    seen = run(tmp_path, "did Status reply about my earbud?")
    sources = seen["user"].split("Sources:", 1)[1]
    first = sources.strip().split("</source>")[0]
    assert "Please pair this earbud" in first  # Oct 1 04:47 UTC, the newest message
    assert "I received the new one" in sources  # your own latest message is there too
    assert "Lead with its newest message" in seen["system"]


def test_other_questions_keep_relevance_order_and_plain_instructions(tmp_path):
    seen = run(tmp_path, "how do I fix the Status earbud app?")
    assert "Lead with its newest message" not in seen["system"]
