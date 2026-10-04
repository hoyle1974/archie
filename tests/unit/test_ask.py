from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from tests.support.fixtures import by_schema, make_ctx, part, question, understood

DOSSIER = "## Priya Sharma\nPriya is the PM for auth. Likes data.\n"


def seeded(tmp_path, replies):
    ctx = make_ctx(tmp_path, FakeBackend(replies))
    atomic_write(ctx.home / "people/priya_sharma.md", DOSSIER)
    ctx.index.sync()
    return ctx


def test_search_answer_keeps_only_verified_claims(tmp_path):
    synth = {"summary": [
        {"text": "Priya is the PM for auth.", "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]},
        {"text": "Priya hates meetings.", "citations": [{"ref": 1, "quote": "Priya hates meetings"}]}],
        "sections": []}
    ctx = seeded(tmp_path, by_schema(understand=understood(question("search", topic="Priya")), answer=synth))
    ans = ask(ctx, "who is priya")
    assert [c.text for c in ans.summary] == ["Priya is the PM for auth."]
    assert ans.dropped == 1


def test_no_hits_says_so_without_calling_synthesis(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("search", topic="zebras"))))
    ctx = make_ctx(tmp_path, fb)
    ans = ask(ctx, "zebras?")
    assert "couldn't find" in render(ans).lower()
    assert [c["shape"].name for c in fb.calls] == ["understand"]


def test_text_replies_run_through_the_real_parser_and_verifier(tmp_path):
    route_text = "PART question\ntext: who is priya\nintent: search\ntopic: Priya"
    answer_text = ('SUMMARY\nPriya is the PM for auth. [1] "Priya is the PM for auth"\n'
                   'Made up. [1] "nothing like this exists"')
    ctx = seeded(tmp_path, by_schema(understand=route_text, answer=answer_text))
    ans = ask(ctx, "who is priya")
    assert [c.text for c in ans.summary] == ["Priya is the PM for auth."]
    assert ans.dropped == 1


def test_everything_unverified_is_reported_honestly(tmp_path):
    synth = {"summary": [{"text": "Made up.", "citations": [{"ref": 1, "quote": "nothing like this exists"}]}],
             "sections": []}
    ctx = seeded(tmp_path, by_schema(understand=understood(question("search", topic="Priya")), answer=synth))
    out = render(ask(ctx, "priya?"))
    assert "couldn't verify" in out.lower()
    assert "Made up" not in out


def test_unknown_intent_falls_back_to_search(tmp_path):
    synth = {"summary": [{"text": "Priya is the PM for auth.",
                          "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    ctx = seeded(tmp_path, by_schema(understand=understood(question("teleport")), answer=synth))
    assert ask(ctx, "priya").summary


def test_help_needs_no_llm(tmp_path):
    fb = FakeBackend(by_schema(understand=understood(question("help"))))
    ctx = make_ctx(tmp_path, fb)
    out = render(ask(ctx, "what can you do?"))
    assert "archie ask" in out
    assert len(fb.calls) == 0  # quick-routed


def test_render_leads_with_summary_and_hides_sources_by_default(tmp_path):
    synth = {"summary": [{"text": "Priya is the PM for auth.",
                          "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}],
             "sections": [{"heading": "Details", "items": [
                 {"text": "Likes data.", "citations": [{"ref": 1, "quote": "Likes data"}]}]}]}
    ctx = seeded(tmp_path, by_schema(understand=understood(question("search", topic="Priya")), answer=synth))
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

    fb = FakeBackend(by_schema(understand=understood(question("search", topic="zebras"))))
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
        reply = understood(part("instruct", text="I picked up the pizza.", action="loop_done"),
                           part("tell", text="Sam is my neighbor.", fact="person"))
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
        out = render(ask(ctx, "I picked up the pizza. Sam is my neighbor."))
    finally:
        HANDLERS.clear()
        HANDLERS.update(saved)
    assert calls == [("loop_update", "I picked up the pizza."), ("remember", "Sam is my neighbor.")]
    assert "Marked done: pizzas" in out and "Got it. I'll remember: X" in out


def test_send_is_refused_plainly_and_nothing_runs(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("instruct", action="send")))))
    assert render(ask(ctx, "email Workpersonthree that the pizza's picked up")) == "I can't send anything; I only read."


def test_an_instruction_with_no_action_says_it_cannot_yet(tmp_path):
    reply = understood(part("instruct", action="none", wanted="filter Today by day"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "only show work stuff on weekdays")) == "I can't do that yet."


def test_unclear_asks_back_with_a_short_question_only(tmp_path):
    reply = understood(part("unclear", ask="Which one: Workpersonthree's pizza or Workpersonfour's form?"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "she's done with it")) == "Which one: Workpersonthree's pizza or Workpersonfour's form?"
    ctx.backend = FakeBackend(by_schema(understand=understood(part("unclear", ask="Workpersonthree is done."))))
    assert render(ask(ctx, "she's done with it")) == "I'm not sure what you mean. Could you say it another way?"


def test_answer_to_who_is_reaches_remember_with_the_address(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all
    from archie.derive.dedupe import save_questions

    load_all()
    seen = []
    saved = dict(HANDLERS)
    HANDLERS["remember"] = lambda ctx, q, p: (seen.append(q), Answer(plain="Got it."))[1]
    try:
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("answer", question=1)))))
        save_questions(ctx.home, [{"id": "q1", "kind": "who_is", "person": "x", "status": "open",
                                   "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
                                   "asked_at": "2026-10-01T00:00:00+00:00"}])
        ask(ctx, "it's my plumber")
    finally:
        HANDLERS.clear()
        HANDLERS.update(saved)
    assert seen == ["a@b.co: it's my plumber"]


def test_each_exchange_is_remembered_with_its_numbered_sources(tmp_path):
    import json

    synth = {"summary": [{"text": "Priya is the PM for auth.", "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}],
             "sections": []}
    reply = understood(question("search", topic="Priya", resolved="Who is Priya?"))
    ctx = seeded(tmp_path, by_schema(understand=reply, answer=synth))
    ask(ctx, "who is priya")
    [entry] = [json.loads(x) for x in (ctx.home / "state/conversation.jsonl").read_text().splitlines()]
    assert entry["said"] == "who is priya" and entry["resolved"] == "Who is Priya?"
    assert entry["citations"][0]["file"] == "people/priya_sharma.md" and entry["citations"][0]["n"] == 1
    assert entry["summary"].startswith("Priya is the PM for auth. [1]")
    log = [json.loads(x) for x in (ctx.home / "logs/usage.jsonl").read_text().splitlines()]
    assert log[0]["parts"] == [{"kind": "question", "handler": "search"}]
