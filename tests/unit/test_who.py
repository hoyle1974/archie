from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx, question, understood
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


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

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("who", people=["Priya"])), answer=answer)))
    seed(ctx)
    out = render(ask(ctx, "who is Priya?"))
    assert out.startswith("Priya asked to ship SSO")
    assert "Priya Sharma" in out
    assert "Last talked: Wed Sep 30, 10:00 AM" in out
    assert "Email you sent: Latency (Wed Sep 30, 10:00 AM)" in out
    assert "2 email threads" in out


def test_ambiguous_name_asks_back_without_llm_synthesis(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("who", people=["Alex"]))))
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    out = render(ask(ctx, "who is Alex?"))
    assert "Which Alex" in out and "Alex Rivera" in out and "Alex Kim" in out
    assert [c["shape"].name for c in fb.calls] == ["understand"]


def test_unknown_person_says_so(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("who", people=["Zed"])))))
    seed(ctx)
    assert "don't know anyone called Zed" in render(ask(ctx, "who is Zed?"))


EMPTY = {"summary": [], "sections": []}


def test_someone_known_only_from_a_telling_gets_a_sentence(tmp_path):
    from archie.ask.remember import apply_facts

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("who", people=["Sam"])),
                                                   answer=EMPTY)))
    seed(ctx)
    apply_facts(ctx, "Sam is my neighbor.", [{"name": "Sam", "relationship": "neighbor",
                                               "statement": "Sam is my neighbor."}])
    ctx.index.sync()
    out = render(ask(ctx, "who is Sam?"))
    assert out.startswith("Sam is your neighbor. That's all I know so far.")


def test_a_stated_relationship_leads_even_when_the_mail_never_says_it(tmp_path):
    from archie.ask.remember import apply_facts

    def answer(system, user, schema, tier):
        ref = next(line for line in user.splitlines() if line.startswith("[") and "SSO dates" in line)[1]
        return {"summary": [{"text": "Priya asked to ship SSO before the Redis migration.",
                             "citations": [{"ref": int(ref), "quote": "ship SSO before the Redis migration"}]}],
                "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("who", people=["Priya"])),
                                                   answer=answer)))
    seed(ctx)
    apply_facts(ctx, "Priya is my manager.", [{"name": "Priya", "relationship": "manager",
                                                "statement": "Priya is my manager."}])
    out = render(ask(ctx, "who is Priya?"))
    assert out.startswith("Priya Sharma is your manager. Priya asked to ship SSO")


def test_webmail_is_not_an_org():
    from archie.ask.intents.who import person_lines
    from archie.derive.people import PeopleDirectory, org_of

    assert org_of("belle@gmail.com") is None and org_of("workpersonthreec@ebsfb.org") == "ebsfb.org"
    directory = PeopleDirectory()
    directory.add("goodspouse", {"entity_id": "goodspouse", "name": "Goodspouse", "aliases": [], "org": "gmail.com"})
    assert not any(line.startswith("Org:") for line in person_lines(directory, "goodspouse", []))


def test_recent_lists_each_thing_once(tmp_path):
    def answer(system, user, schema, tier):
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(question("who", people=["Priya"])),
                                                   answer=answer)))
    same = [write_thread(ctx.home, f"d{i}", [msg(f"d{i}", "priya@acme.example", "Priya Sharma", [addr(TEST)],
                                               "2026-09-29T17:00:00+00:00", "Agenda attached", subject="Team sync",
                                               to_me=True)]) for i in range(3)]
    derive_people(ctx, same)
    ctx.index.sync()
    out = render(ask(ctx, "who is Priya?"))
    assert out.count("Team sync") == 1
