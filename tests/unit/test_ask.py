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


def test_mixed_message_runs_every_part(tmp_path, monkeypatch):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all

    load_all()
    calls = []
    monkeypatch.setitem(HANDLERS, "loop_update",
                        lambda ctx, q, p: (calls.append(q), Answer(plain="Marked done: pizzas"))[1])
    sam = {"people": [{"name": "Sam", "relationship": "neighbor", "role": None, "pronouns": None, "identity": None,
                       "avoid": [], "other_names": [], "statement": "Sam is my neighbor."}]}
    reply = understood(part("instruct", text="I picked up the pizza.", action="loop_done"),
                       part("tell", text="Sam is my neighbor.", fact="person"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply, remember=sam)))
    out = render(ask(ctx, "I picked up the pizza. Sam is my neighbor."))
    assert calls == ["I picked up the pizza."]
    assert "Marked done: pizzas" in out and "Sam (neighbor), new" in out
    assert ctx.backend.calls[-1]["user"] == "Sam is my neighbor."


def test_send_is_refused_plainly_and_nothing_runs(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("instruct", action="send")))))
    assert render(ask(ctx, "email Workpersonthree that the pizza's picked up")) == "I can't send anything; I only read."


def test_an_instruction_with_no_action_says_it_cannot_yet(tmp_path):
    reply = understood(part("instruct", action="none", wanted="filter Today by day"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "only show work stuff on weekdays")) == "I can't do that yet."


def test_unclear_asks_back_with_a_short_question_only(tmp_path):
    reply = understood(part("unclear", ask="Which one do you mean: the pizza or the form?"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, "she's done with it")) == "Which one do you mean: the pizza or the form?"
    for made_up in ("The pizza is done.", "Do you mean Workpersonthree's pizza?"):  # not a question; a name nobody said
        ctx.backend = FakeBackend(by_schema(understand=understood(part("unclear", ask=made_up))))
        assert render(ask(ctx, "she's done with it")) == "I'm not sure what you mean. Could you say it another way?"


def test_answer_to_who_is_reaches_remember_with_the_address(tmp_path):
    from archie.derive.dedupe import save_questions

    seen = []
    model = by_schema(understand=understood(part("answer", question=1)),
                      remember=lambda s, u, sh, t: (seen.append(u), {"people": []})[1])
    ctx = make_ctx(tmp_path, FakeBackend(model))
    save_questions(ctx.home, [{"id": "q1", "kind": "who_is", "person": "x", "status": "open",
                               "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
                               "asked_at": "2026-10-01T00:00:00+00:00"}])
    ask(ctx, "it's my plumber")
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


def _with_handlers(**fns):
    from archie.ask.intents import HANDLERS, load_all

    load_all()
    saved = dict(HANDLERS)
    HANDLERS.update(fns)
    return saved


def _restore(saved):
    from archie.ask.intents import HANDLERS

    HANDLERS.clear()
    HANDLERS.update(saved)


def test_two_cited_parts_share_one_numbering(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.render import citations_of
    from archie.llm.verify import Citation, Claim

    ken = Citation(1, "sources/gmail/k.json", "c0", "budget is flat", "Ken, Oct 1")
    priya = Citation(1, "people/priya_sharma.md", "c0", "Priya is your manager", "Priya (dossier)")
    saved = _with_handlers(search=lambda ctx, q, p: Answer(summary=[Claim("Ken said the budget is flat.", [ken])]),
                           who=lambda ctx, q, p: Answer(summary=[Claim("Priya is your manager.", [priya])]))
    try:
        reply = understood(question("search", text="what did Ken say?"), question("who", text="who is Priya?"))
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply)))
        ans = ask(ctx, "what did Ken say? who is Priya?")
    finally:
        _restore(saved)
    out = render(ans, sources=True)
    assert "Ken said the budget is flat. [1]" in out and "Priya is your manager. [2]" in out
    assert [c["file"] for c in citations_of(ans)] == ["sources/gmail/k.json", "people/priya_sharma.md"]


def test_a_plain_reply_then_a_cited_one_keeps_the_sources(tmp_path):
    from archie.ask.answer import Answer
    from archie.ask.render import citations_of
    from archie.llm.verify import Citation, Claim

    priya = Citation(1, "people/priya_sharma.md", "c0", "Priya is your manager", "Priya (dossier)")
    sam = {"people": [{"name": "Sam", "relationship": "neighbor", "statement": "Sam is my neighbor."}]}
    saved = _with_handlers(who=lambda ctx, q, p: Answer(summary=[Claim("Priya is your manager.", [priya])]))
    try:
        reply = understood(part("tell", text="Sam is my neighbor."), question("who", text="who is Priya?"))
        ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply, remember=sam)))
        ans = ask(ctx, "Sam is my neighbor. who is Priya?")
    finally:
        _restore(saved)
    out = render(ans)
    assert out.startswith("Got it. I'll remember:\n  • Sam (neighbor), new") and "Priya is your manager. [1]" in out
    assert [c["file"] for c in citations_of(ans)] == ["people/priya_sharma.md"]


def test_really_after_something_that_was_not_a_question_does_not_redo_it(tmp_path):
    told = []

    def model(system, user, shape, tier):
        msg = user.rsplit("Message:", 1)[-1].strip()
        return understood(part("unclear", ask="Really what?") if msg == "really?" else part("tell"))

    remember = lambda s, u, sh, t: (told.append(u), {"people": []})[1]  # noqa: E731
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=model, remember=remember)))
    ask(ctx, "Sam is my neighbor.")
    out = render(ask(ctx, "really?"))
    assert told == ["Sam is my neighbor."] and not out.startswith("I checked again.")


def test_a_failed_conversation_write_does_not_lose_the_answer(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    (ctx.home / "state/conversation.jsonl").mkdir(parents=True)
    assert "archie ask" in render(ask(ctx, "help"))


def test_show_without_a_clear_number_asks_which_and_keeps_the_sources(tmp_path):
    import json

    synth = {"summary": [{"text": "Priya is the PM for auth.", "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}],
             "sections": []}

    def model(system, user, shape, tier):
        if shape.name == "answer":
            return synth
        msg = user.rsplit("Message:", 1)[-1].strip()
        if msg.startswith("show"):
            return understood(part("instruct", action="show_citation"))
        return understood(question("search", topic="Priya"))

    ctx = seeded(tmp_path, model)
    ask(ctx, "who is priya")
    assert render(ask(ctx, "show me the Oct 2 one")) == 'Which source? Say, for example, "show 2".'
    entries = [json.loads(x) for x in (ctx.home / "state/conversation.jsonl").read_text().splitlines()]
    assert entries[-1]["citations"] == entries[0]["citations"] and entries[0]["citations"]
