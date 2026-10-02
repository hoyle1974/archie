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
    assert [c["schema"]["title"] for c in fb.calls] == ["route"]


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
    assert len(fb.calls) == 1


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
    assert "people/priya_sharma.md" in render(ans, sources=True)
