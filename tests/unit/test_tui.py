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
