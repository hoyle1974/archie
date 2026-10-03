import asyncio

from archie.connectors.base import SyncResult
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write
from archie.tui.app import ArchieApp
from tests.support.fixtures import by_schema, make_ctx


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
    route = {"intent": "search", "params": {"people": [], "since": None, "until": None, "topic": "Priya",
                                            "meeting": None, "text": None}}
    answer = {"summary": [{"text": "Priya is the PM for auth.",
                           "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(route=route, answer=answer)))
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
