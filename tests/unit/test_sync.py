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
