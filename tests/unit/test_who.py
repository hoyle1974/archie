from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def route_who(name):
    return {"intent": "who", "params": {"people": [name], "since": None, "until": None, "topic": None,
                                        "meeting": None, "text": None}}


def seed(ctx):
    paths = [
        write_thread(ctx.home, "t1", [msg("m1", "priya@acme.example", "Priya Sharma", [addr(TEST)],
                                          "2026-09-22T17:00:00+00:00", "Can we ship SSO before the Redis migration?",
                                          subject="SSO dates", to_me=True)]),
        write_thread(ctx.home, "t2", [msg("m2", TEST, "Test", [addr("priya@acme.example", "Priya Sharma")],
                                          "2026-09-30T17:00:00+00:00", "Here is the latency graph you wanted.",
                                          subject="Latency", from_me=True)]),
        write_thread(ctx.home, "t3", [msg("m3", "alex@acme.example", "Alex Rivera", [addr(TEST)],
                                          "2026-09-30T18:00:00+00:00", "PR is up", to_me=True)]),
        write_thread(ctx.home, "t4", [msg("m4", "alex.k@other.example", "Alex Kim", [addr(TEST)],
                                          "2026-09-30T18:00:00+00:00", "hello", to_me=True)]),
    ]
    derive_people(ctx, paths)
    ctx.index.sync()


def test_who_lists_code_computed_facts_and_cited_summary(tmp_path):
    def answer(system, user, schema, tier):
        assert "latency graph" in user  # recent interactions are in the packet
        ref = next(line for line in user.splitlines() if line.startswith("[") and "SSO dates" in line)[1]
        return {"summary": [{"text": "Priya asked to ship SSO before the Redis migration.",
                             "citations": [{"ref": int(ref), "quote": "ship SSO before the Redis migration"}]}],
                "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route_who("Priya"), answer=answer)))
    seed(ctx)
    out = render(ask(ctx, "who is Priya?"))
    assert out.startswith("Priya asked to ship SSO")
    assert "Priya Sharma" in out
    assert "Last talked: Sep 30" in out
    assert "Email you sent: Latency (Sep 30)" in out
    assert "2 email threads" in out


def test_ambiguous_name_asks_back_without_llm_synthesis(tmp_path):
    fb = FakeBackend(by_schema(route=route_who("Alex")))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    out = render(ask(ctx, "who is Alex?"))
    assert "Which Alex" in out and "Alex Rivera" in out and "Alex Kim" in out
    assert [c["shape"].name for c in fb.calls] == ["route"]


def test_unknown_person_says_so(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route_who("Zed"))))
    seed(ctx)
    assert "don't know anyone called Zed" in render(ask(ctx, "who is Zed?"))
