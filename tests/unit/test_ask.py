from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from tests.support.fixtures import by_schema, make_ctx

DOSSIER = "## Priya Sharma\nPriya is the PM for auth. Likes data.\n"


def seeded(tmp_path, replies):
    ctx = make_ctx(tmp_path, FakeBackend(replies))
    atomic_write(ctx.home / "people/priya_sharma.md", DOSSIER)
    ctx.index.sync()
    return ctx


def route(intent, **params):
    return {"intent": intent, "params": {"people": [], "since": None, "until": None, "topic": None, **params}}


def test_search_answer_keeps_only_verified_claims(tmp_path):
    synth = {"summary": [
        {"text": "Priya is the PM for auth.", "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]},
        {"text": "Priya hates meetings.", "citations": [{"ref": 1, "quote": "Priya hates meetings"}]}],
        "sections": []}
    ctx = seeded(tmp_path, by_schema(route=route("search", topic="Priya"), answer=synth))
    ans = ask(ctx, "who is priya")
    assert [c.text for c in ans.summary] == ["Priya is the PM for auth."]
    assert ans.dropped == 1


def test_no_hits_says_so_without_calling_synthesis(tmp_path):
    fb = FakeBackend(by_schema(route=route("search", topic="zebras")))
    ctx = make_ctx(tmp_path, fb)
    ans = ask(ctx, "zebras?")
    assert "couldn't find" in render(ans).lower()
    assert [c["shape"].name for c in fb.calls] == ["route"]


def test_text_replies_run_through_the_real_parser_and_verifier(tmp_path):
    route_text = "intent: search\npeople: -\nsince: -\nuntil: -\ntopic: Priya\nmeeting: -\ntext: -"
    answer_text = ('SUMMARY\nPriya is the PM for auth. [1] "Priya is the PM for auth"\n'
                   'Made up. [1] "nothing like this exists"')
    ctx = seeded(tmp_path, by_schema(route=route_text, answer=answer_text))
    ans = ask(ctx, "who is priya")
    assert [c.text for c in ans.summary] == ["Priya is the PM for auth."]
    assert ans.dropped == 1


def test_everything_unverified_is_reported_honestly(tmp_path):
    synth = {"summary": [{"text": "Made up.", "citations": [{"ref": 1, "quote": "nothing like this exists"}]}],
             "sections": []}
    ctx = seeded(tmp_path, by_schema(route=route("search", topic="Priya"), answer=synth))
    out = render(ask(ctx, "priya?"))
    assert "couldn't verify" in out.lower()
    assert "Made up" not in out


def test_unknown_intent_falls_back_to_search(tmp_path):
    synth = {"summary": [{"text": "Priya is the PM for auth.",
                          "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    ctx = seeded(tmp_path, by_schema(route=route("teleport"), answer=synth))
    assert ask(ctx, "priya").summary


def test_help_needs_no_llm(tmp_path):
    fb = FakeBackend(by_schema(route=route("help")))
    ctx = make_ctx(tmp_path, fb)
    out = render(ask(ctx, "what can you do?"))
    assert "archie ask" in out
    assert len(fb.calls) == 0  # quick-routed


def test_render_leads_with_summary_and_hides_sources_by_default(tmp_path):
    synth = {"summary": [{"text": "Priya is the PM for auth.",
                          "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}],
             "sections": [{"heading": "Details", "items": [
                 {"text": "Likes data.", "citations": [{"ref": 1, "quote": "Likes data"}]}]}]}
    ctx = seeded(tmp_path, by_schema(route=route("search", topic="Priya"), answer=synth))
    ans = ask(ctx, "priya")
    out = render(ans)
    assert out.splitlines()[0].startswith("Priya is the PM for auth. [1]")
    assert "people/priya_sharma.md" not in out
    assert "Details" in out
    with_sources = render(ans, sources=True)
    assert "Sources" in with_sources and "people/priya_sharma.md" not in with_sources  # labels, not paths
    assert "people/priya_sharma.md" in render(ans, sources=True, paths=True)


def test_obvious_questions_skip_the_routing_call(tmp_path):
    from archie.ask.router import quick_route

    assert quick_route("what should I work on next?") == "next"
    assert quick_route("What do I owe people?") == "loops"
    assert quick_route("what am I waiting on") == "loops"
    assert quick_route("help") == "help"
    assert quick_route("what do I owe Sarah?") is None  # names need the router's parameters
    assert quick_route("who is Priya?") is None
    fb = FakeBackend([])
    ctx = make_ctx(tmp_path, fb)
    assert "archie ask" in render(ask(ctx, "what can you do?"))
    assert fb.calls == []


def test_each_question_is_logged_locally(tmp_path):
    import json

    fb = FakeBackend(by_schema(route=route("search", topic="zebras")))
    ctx = make_ctx(tmp_path, fb)
    ask(ctx, "zebras?")
    ask(ctx, "help")
    lines = [json.loads(x) for x in (ctx.home / "logs/usage.jsonl").read_text().splitlines()]
    assert [x["intent"] for x in lines] == ["search", "help"]
    assert lines[0]["nothing_found"] is True and lines[1]["quick"] is True
    assert all("ms" in x and x["question"] for x in lines)
    assert "couldn't find" in lines[0]["answer"] and "archie ask" in lines[1]["answer"]


def test_mixed_message_runs_every_part(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all

    load_all()
    calls = []
    monkey_loop = lambda ctx, q, p: (calls.append(("loop_update", q)), Answer(plain="Marked done: pizzas"))[1]  # noqa
    monkey_rem = lambda ctx, q, p: (calls.append(("remember", q)), Answer(plain="Got it. I'll remember: X"))[1]  # noqa
    saved = dict(HANDLERS)
    HANDLERS.update(loop_update=monkey_loop, remember=monkey_rem)
    try:
        said = "I picked up the pizza. Sam is my neighbor."
        r = route("remember")
        r["also"] = [{"intent": "loop_update", "text": "I picked up the pizza."}]
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=r)))
        out = render(ask(ctx, said))
    finally:
        HANDLERS.clear()
        HANDLERS.update(saved)
    assert calls == [("remember", said), ("loop_update", "I picked up the pizza.")]
    assert "Got it. I'll remember: X" in out and "Marked done: pizzas" in out


def test_also_part_whose_words_are_not_in_the_message_gets_the_whole_message(tmp_path):
    from archie.ask.router import split_parts

    assert split_parts("A. B.", [{"intent": "loop_update", "text": "invented"}], "remember") == \
        [("loop_update", "A. B.")]
    assert split_parts("A. B.", [{"intent": "remember", "text": "B."}], "remember") == []  # same intent: no repeat


def test_part_words_match_despite_collapsed_spaces():
    from archie.ask.router import split_parts

    assert split_parts("I left.  Sam is my neighbor.", [{"intent": "remember", "text": "Sam is my neighbor."}],
                       "loop_update") == [("remember", "Sam is my neighbor.")]
