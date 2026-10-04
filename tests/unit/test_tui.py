import asyncio

from textual.widgets import Static

from archie.connectors.base import SyncResult
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from archie.tui.app import ArchieApp
from tests.support.fixtures import by_schema, make_ctx, question, understood


class Counting:
    name = "gmail"

    def __init__(self):
        self.calls = 0

    async def sync(self, sctx, cursor):
        self.calls += 1
        return SyncResult(cursor={"n": self.calls})


def text_of(app, selector):
    return str(app.query_one(selector).render())


def test_launch_runs_catch_up_sync_and_shows_status(tmp_path):
    ctx = make_ctx(tmp_path)
    conn = Counting()

    async def go():
        app = ArchieApp(ctx, connectors=[conn], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert conn.calls == 1
            assert "gmail: ok" in text_of(app, "#activity")

    asyncio.run(go())


def test_sync_pane_shows_what_sync_is_waiting_on(tmp_path):
    ctx = make_ctx(tmp_path)
    release = asyncio.Event()

    class Stuck:
        name = "gmail"

        async def sync(self, sctx, cursor):
            await release.wait()
            return SyncResult(cursor={})

    async def go():
        app = ArchieApp(ctx, connectors=[Stuck()], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "Waiting on gmail…" in text_of(app, "#activity")
            release.set()
            await app.sync_done.wait()
            await pilot.pause()
            assert "gmail: ok" in text_of(app, "#activity")

    asyncio.run(go())


def test_question_in_ask_pane_shows_answer(tmp_path):
    route = understood(question("search", topic="Priya"))
    answer = {"summary": [{"text": "Priya is the PM for auth.",
                           "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=route, answer=answer)))
    atomic_write(ctx.home / "people/priya.md", "## Priya\nPriya is the PM for auth.\n")
    ctx.index.sync()

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await pilot.click("#question")
            await pilot.press(*"who is priya", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            assert "Priya is the PM for auth. [1]" in text_of(app, "#answer")

    asyncio.run(go())


def test_feed_shows_builder_output(tmp_path):
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], feed=lambda c: "Nothing scheduled today.", ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert "Nothing scheduled today." in text_of(app, "#feed")

    asyncio.run(go())


def test_copy_uses_pbcopy_and_ctrl_y_copies_the_answer(tmp_path, monkeypatch):
    import archie.tui.app as tui

    copied = []
    monkeypatch.setattr(tui, "_pbcopy", lambda text: copied.append(text))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            app.copy_to_clipboard("selected bit")
            await pilot.press("ctrl+y")
            await pilot.pause()

    asyncio.run(go())
    assert copied[0] == "selected bit"
    assert "Ask anything" in copied[1]


def test_second_window_does_not_sync(tmp_path):
    from archie.store.lock import WriterLock

    ctx = make_ctx(tmp_path)
    conn = Counting()
    held = WriterLock(ctx.home.root)
    assert held.acquire()

    async def go():
        app = ArchieApp(ctx, connectors=[conn], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert conn.calls == 0 and "Another Archie window" in text_of(app, "#activity")

    asyncio.run(go())
    held.release()


def test_slow_answer_times_out_with_a_message(tmp_path, monkeypatch):
    import time as _time

    import archie.tui.app as tui

    monkeypatch.setattr(tui, "ASK_TIMEOUT", 0.3)
    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q: _time.sleep(2))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.click("#question")
            await pilot.press(*"slow", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            assert "took too long" in text_of(app, "#answer")

    asyncio.run(go())


def test_ask_pane_shows_gemini_spend_and_keeps_it_current(tmp_path):
    from archie.llm.budget import Budget

    ctx = make_ctx(tmp_path)
    ctx.backend.budget = Budget(ctx.home, 15)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            pane = app.query_one("#answer-scroll")
            assert pane.border_subtitle == "Gemini: $0.00 of $15 this month"
            ctx.backend.budget.record("gemini-3.7-flash", "fast", 28_000, 0, 0)
            app.refresh_spend()
            await pilot.pause()
            assert pane.border_subtitle == "Gemini: $0.02 of $15 this month"

    asyncio.run(go())


def test_sync_shows_googles_token_count_and_warns_when_out_of_step(tmp_path, monkeypatch):
    from archie.llm import google_usage
    from archie.llm.budget import Budget

    ctx = make_ctx(tmp_path)
    ctx.backend.budget = Budget(ctx.home, 15)
    ctx.config["llm"]["google_project"] = "archie-email"
    real_check = google_usage.check

    def check(home, project, now=None, get=None):
        def google(path, params):
            if path.endswith("/metricDescriptors"):
                return {"metricDescriptors": []}
            return {"timeSeries": [{"metric": {"labels": {"model": "gemini-3.7-flash"}},
                                    "points": [{"value": {"int64Value": "400000"}}]}]}  # $1.50 of output
        return real_check(home, project, now, google)

    monkeypatch.setattr(google_usage, "check", check)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert ("Warning: Google counts $1.50 more Gemini use this month than Archie logged ($1.50 vs $0.00)"
                    in text_of(app, "#activity"))
            assert app.query_one("#answer-scroll").border_subtitle == \
                "Gemini: $0.00 of $15 this month · Google: $1.50, out of step"

    asyncio.run(go())


def test_a_long_sync_report_scrolls_instead_of_being_cut_off(tmp_path):
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            long = "\n".join(f"line {i}: Google's token count: couldn't check (a long reason)" for i in range(20))
            app.query_one("#activity", Static).update(long)
            await pilot.pause()
            pane = app.query_one("#activity-scroll")
            assert pane.border_title == "Sync" and pane.max_scroll_y > 0
            pane.scroll_end(animate=False)
            await pilot.pause()
            assert pane.scroll_y == pane.max_scroll_y

    asyncio.run(go())


def test_today_pane_refreshes_after_an_answer(tmp_path, monkeypatch):
    from archie.ask.answer import Answer

    state = {"feed": "before"}
    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q: (state.update(feed="after"), Answer(plain="Done."))[1])
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], feed=lambda c: state["feed"], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert "before" in text_of(app, "#feed")
            await pilot.click("#question")
            await pilot.press(*"done with it", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            assert "after" in text_of(app, "#feed")

    asyncio.run(go())
