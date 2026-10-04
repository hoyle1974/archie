import asyncio

import yaml

from archie.connectors.base import SyncResult
from archie.store.files import write_raw
from archie.sync import run_cycle
from tests.support.fixtures import make_ctx


class Good:
    name = "good"

    def __init__(self):
        self.seen_cursor = "unset"

    async def sync(self, sctx, cursor):
        self.seen_cursor = cursor
        path = sctx.home / "sources/good/1.json"
        write_raw(path, {"n": (cursor or {}).get("n", 0) + 1})
        return SyncResult(cursor={"n": (cursor or {}).get("n", 0) + 1}, written=[path])


class Broken:
    name = "broken"

    async def sync(self, sctx, cursor):
        raise RuntimeError("token expired")


def test_cycle_saves_cursor_and_isolates_failures(tmp_path):
    ctx = make_ctx(tmp_path)
    good, seen = Good(), []
    report = asyncio.run(run_cycle(ctx, [good, Broken()], derivers=[lambda c, paths: seen.extend(paths)]))
    assert report["good"].ok and not report["broken"].ok
    assert "token expired" in report["broken"].error
    cursors = yaml.safe_load(ctx.home.cursors_file.read_text())
    assert cursors == {"good": {"n": 1}}
    assert [p.name for p in seen] == ["1.json"]


def test_cursor_is_passed_back_next_cycle(tmp_path):
    ctx = make_ctx(tmp_path)
    good = Good()
    asyncio.run(run_cycle(ctx, [good]))
    asyncio.run(run_cycle(ctx, [good]))
    assert good.seen_cursor == {"n": 1}


def test_failed_connector_keeps_previous_cursor(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.home.cursors_file.write_text("broken: {page: 7}\n")
    asyncio.run(run_cycle(ctx, [Broken()]))
    assert yaml.safe_load(ctx.home.cursors_file.read_text()) == {"broken": {"page": 7}}


def test_cycle_indexes_new_files(tmp_path):
    ctx = make_ctx(tmp_path)
    from archie.index.chunk import Chunk, register_raw_chunker

    register_raw_chunker("good", lambda p, d: [Chunk("c0", p, 0, 0, f"counter {d['n']}", source="good")])
    asyncio.run(run_cycle(ctx, [Good()]))
    assert ctx.index.counts()["files"] == 1


def test_status_file_records_last_success(tmp_path):
    ctx = make_ctx(tmp_path)
    asyncio.run(run_cycle(ctx, [Good(), Broken()]))
    status = yaml.safe_load((ctx.home / "state/sync_status.yaml").read_text())
    assert status["good"]["last_success"] and status["broken"]["last_error"] == "token expired"


def test_a_failure_stays_explained_after_the_next_success(tmp_path):
    class Flaky(Good):
        name = "flaky"
        calls = 0

        async def sync(self, sctx, cursor):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("timed out")
            return await super().sync(sctx, cursor)

    ctx = make_ctx(tmp_path)
    asyncio.run(run_cycle(ctx, [Flaky()]))
    asyncio.run(run_cycle(ctx, [Flaky()]))
    status = yaml.safe_load((ctx.home / "state/sync_status.yaml").read_text())["flaky"]
    assert status["last_error"] is None and status["last_failure_error"] == "timed out"
    log = (ctx.home / "logs/errors.log").read_text()
    assert "sync: flaky" in log and "RuntimeError: timed out" in log


def test_disabled_google_api_error_is_explained(tmp_path):
    class Off:
        name = "calendar"

        async def sync(self, sctx, cursor):
            raise RuntimeError('<HttpError 403 when requesting https://x returned "Google Calendar API has not been '
                               'used in project 767842269502 before or it is disabled. Enable it by visiting '
                               'https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview'
                               '?project=767842269502 then retry.">')

    ctx = make_ctx(tmp_path)
    report = asyncio.run(run_cycle(ctx, [Off()]))
    err = report["calendar"].error
    assert err.startswith("Google Calendar API is switched off for your Google project. Enable it:")
    assert "https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=767842269502" in err


def test_after_chains_run_in_dependency_order(tmp_path):
    ctx, order = make_ctx(tmp_path), []

    def conn(name, after=()):
        async def sync(sctx, cursor):
            order.append(name)
            return SyncResult(cursor={}, written=[])
        return type(name, (), {"name": name, "after": after, "sync": staticmethod(sync)})()

    report = asyncio.run(run_cycle(ctx, [conn("c", ("b",)), conn("b", ("a",)), conn("a")], index=False))
    assert order == ["a", "b", "c"]
    assert list(report) == ["c", "b", "a"]


def test_progress_says_what_sync_is_waiting_on(tmp_path):
    ctx, said = make_ctx(tmp_path), []
    fast_done = asyncio.Event()

    class Fast:
        name = "calendar"

        async def sync(self, sctx, cursor):
            fast_done.set()
            return SyncResult(cursor={}, written=[])

    class Slow:
        name = "gmail"

        async def sync(self, sctx, cursor):
            await fast_done.wait()
            await asyncio.sleep(0)  # let the calendar finish being reported first
            return SyncResult(cursor={}, written=[])

    def derive_loops(c, paths):
        pass

    asyncio.run(run_cycle(ctx, [Slow(), Fast()], derivers=[derive_loops], post_index=[lambda c: None],
                          on_progress=said.append))
    assert said[0] == "Waiting on calendar, gmail…"
    assert "Waiting on gmail…" in said
    assert said[said.index("Waiting on gmail…") + 1:] == [
        "Reading what's new: loops…", "Updating the search index…", "Final checks…"]
