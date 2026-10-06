"""The dig loop's web step (spec: dig-deeper §3): links from the backend, pages fetched within
limits, saved under sources/web/, indexed, cited with a "Web:" label."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from archie.ask.dig import dig
from archie.connectors.web import page_path, public, query_problem, web_search
from archie.llm.backend import FakeBackend, GeminiBackend
from archie.store.files import read_raw
from tests.support.fake_web import FakeWeb, html, page, redirect
from tests.support.fixtures import by_schema, make_ctx

ABOUT = ("Workpersontwo Birch is a talent partner at Overwatch Data, where she helps new engineers settle in. "
         "Before that she ran recruiting operations at a robotics startup for six years, and she "
         "speaks at hiring meetups.")
URL = "https://example.org/workpersontwo"


class Linker(FakeBackend):
    def __init__(self, links, replies=None):
        super().__init__(replies or [])
        self.links, self.asked = links, []

    def web_links(self, query, n=3):
        self.asked.append(query)
        return self.links.get(query, [])[:n]


def ctx_with(tmp_path, pages, links=None, replies=None):
    ctx = make_ctx(tmp_path, Linker(links or {"Workpersontwo Birch": [{"url": URL, "title": "example.org"}]}, replies),
                   dig=True)
    ctx.web = FakeWeb(pages)
    return ctx


@pytest.mark.parametrize("query, problem", [
    ("workpersontwo@example.org", "email address"), ("https://evil.example/x", "link"),
    ("order 123456 status", "long numbers"), ("one two three four five six seven eight nine", "at most 8 words")])
def test_queries_that_could_leak_mail_are_refused(query, problem):
    assert problem in query_problem(query)


def test_a_fair_query_passes():
    assert query_problem("Workpersontwo Birch Overwatch Data") is None


def test_a_page_is_saved_indexed_and_labelled(tmp_path):
    ctx = ctx_with(tmp_path, {URL: page(html("Workpersontwo Birch – Overwatch Data", ABOUT))})
    chunks = web_search(ctx, "Workpersontwo Birch")
    saved = read_raw(ctx.home / page_path(URL))
    assert saved["url"] == URL and saved["title"] == "Workpersontwo Birch – Overwatch Data"
    assert saved["query"] == "Workpersontwo Birch" and saved["fetched_at"] == ctx.now.isoformat()
    assert "var x" not in saved["text"] and "Home | About" not in saved["text"] and ABOUT in saved["text"]
    assert chunks and chunks[0]["label"] == "Web: Workpersontwo Birch – Overwatch Data (fetched Oct 1)"
    assert ctx.index.chunks_of(page_path(URL))


def test_a_redirect_is_saved_under_its_final_address(tmp_path):
    hop = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    ctx = ctx_with(tmp_path, {hop: page(html("Workpersontwo", ABOUT), final=URL)},
                   links={"Workpersontwo Birch": [{"url": hop, "title": "example.org"}]})
    web_search(ctx, "Workpersontwo Birch")
    assert (ctx.home / page_path(URL)).exists()


@pytest.mark.parametrize("bad", [
    page(html("x", ABOUT), status=403), page(b"%PDF-1.4", kind="application/pdf"),
    page(html("Login", "Sign in to continue.")), page("x" * 2_000_001, kind="text/plain"),
    page("", error=TimeoutError("slow"))], ids=["status", "type", "too short", "too big", "timeout"])
def test_unreadable_pages_are_skipped(tmp_path, bad):
    ctx = ctx_with(tmp_path, {URL: bad})
    assert web_search(ctx, "Workpersontwo Birch") == []
    assert not (ctx.home / "sources/web").exists() or not list((ctx.home / "sources/web").iterdir())


def test_redirect_hops_are_followed_and_each_one_checked(tmp_path):
    hop = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    links = {"Workpersontwo Birch": [{"url": hop, "title": "example.org"}]}
    ctx = ctx_with(tmp_path / "ok", {hop: redirect("/next"), "https://vertexaisearch.cloud.google.com/next":
                                     redirect(URL), URL: page(html("Workpersontwo Birch", ABOUT))}, links=links)
    assert web_search(ctx, "Workpersontwo Birch") and (ctx.home / page_path(URL)).exists()
    for bad in ("http://example.org/workpersontwo", "https://192.168.1.1/admin", "https://localhost/x",
                "https://printer.local/"):
        ctx = ctx_with(tmp_path / str(abs(hash(bad))), {hop: redirect(bad)}, links=links)
        assert web_search(ctx, "Workpersontwo Birch") == [], bad
        assert ctx.web.requests == [hop], bad  # the bad hop is never requested


def test_only_public_https_addresses_are_allowed():
    assert public("https://example.org/a", resolve=False)
    for bad in ("http://example.org/", "https://10.0.0.8/", "https://[::1]/", "https://169.254.169.254/latest",
                "https://router.lan/", "ftp://example.org/"):
        assert not public(bad, resolve=False), bad


def test_plain_http_is_never_fetched(tmp_path):
    ctx = ctx_with(tmp_path, {}, links={"Workpersontwo Birch": [{"url": "http://example.org/p", "title": ""}]})
    assert web_search(ctx, "Workpersontwo Birch") == [] and ctx.web.requests == []


def test_a_page_fetched_this_week_is_reused(tmp_path):
    ctx = ctx_with(tmp_path, {URL: page(html("Workpersontwo", ABOUT))})
    web_search(ctx, "Workpersontwo Birch")
    ctx.now += timedelta(days=6)
    web_search(ctx, "Workpersontwo Birch")
    assert ctx.web.read == [URL]  # the second time only the headers were looked at
    ctx.now += timedelta(days=2)
    web_search(ctx, "Workpersontwo Birch")
    assert ctx.web.read == [URL, URL]


def test_dig_cites_a_web_page_with_its_label(tmp_path):
    from archie.ask.render import render

    def answer(system, user, shape, tier):
        assert 'from a web page' in system
        return {"summary": [{"text": "According to a web page, Workpersontwo is a talent partner at Overwatch Data.",
                             "citations": [{"ref": 1, "quote": "talent partner at Overwatch Data"}]}], "sections": []}

    steps = [{"do": "web", "arg": "Workpersontwo Birch"}, {"do": "answer"}]
    ctx = ctx_with(tmp_path, {URL: page(html("Workpersontwo Birch – Overwatch Data", ABOUT))},
                   replies=by_schema(dig_step=lambda *a: steps.pop(0), answer=answer))
    r = dig(ctx, "who is Workpersontwo?", "no file on anyone called Workpersontwo")
    out = render(r.answer, sources=True)
    assert "[1] Web: Workpersontwo Birch – Overwatch Data (fetched Oct 1)" in out
    assert out.splitlines()[-1] != "I looked further: 1 web search."  # sources come last
    assert "I looked further: 1 web search." in out
    assert "- web:" in ctx.backend.calls[0]["system"]


def test_dig_refuses_a_leaky_web_query_and_web_can_be_switched_off(tmp_path):
    steps = [{"do": "web", "arg": "workperson@overwatchdata.io"}]
    ctx = ctx_with(tmp_path, {}, replies=by_schema(dig_step=lambda *a: steps.pop(0) if steps else {"do": "answer"}))
    r = dig(ctx, "q", "nothing")
    assert r.actions == ["refused: web: workperson@overwatchdata.io"] and ctx.backend.asked == []
    ctx.config["ask"]["dig"]["web"] = False
    steps.append({"do": "web", "arg": "Workpersontwo Birch"})
    r = dig(ctx, "q", "nothing")
    assert r.actions == ["refused: web: Workpersontwo Birch"]


def test_gemini_web_links_reads_only_grounding_sources_and_records_the_fee(tmp_path):
    from archie.llm.budget import GROUNDED_CALL_USD, Budget
    from archie.store.home import init_home

    web = lambda uri, title: SimpleNamespace(web=SimpleNamespace(uri=uri, title=title))  # noqa: E731
    resp = SimpleNamespace(
        text="Workpersontwo Birch is famous for many things.",
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=0),
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=[
            web("https://a.example/1", "a.example"), web("https://a.example/1", "a.example"),
            web("https://b.example/2", "b.example"), SimpleNamespace(web=None)]))])

    class Client:
        def __init__(self):
            self.models, self.calls = self, []

        def generate_content(self, model, contents, config):
            self.calls.append((model, contents, config))
            return resp

    client = Client()
    budget = Budget(init_home(tmp_path / "home"), 15)
    b = GeminiBackend({"models": {"fast": "flash-x"}}, client=client, budget=budget)
    assert b.web_links("Workpersontwo Birch") == [{"url": "https://a.example/1", "title": "a.example"},
                                               {"url": "https://b.example/2", "title": "b.example"}]
    model, contents, config = client.calls[0]
    assert model == "flash-x" and "Workpersontwo Birch" in contents and config.tools[0].google_search is not None
    assert budget.session_usd >= GROUNDED_CALL_USD
