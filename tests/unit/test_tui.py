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
    return str(app.query(selector).last().render())


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
            assert "Priya is the PM for auth. [1]" in text_of(app, ".answer")

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


def test_offers_to_reconnect_google_and_resyncs(tmp_path, monkeypatch):
    from archie.connectors import google_auth

    class Dead:
        name = "gmail"
        calls = 0

        async def sync(self, sctx, cursor):
            Dead.calls += 1
            if Dead.calls == 1:
                raise google_auth.NeedsAuth(f"Google access expired: run `{google_auth.RECONNECT_HINT}`")
            return SyncResult(cursor={})

    connected = []
    monkeypatch.setattr(google_auth, "connect", lambda client, sources: connected.append(sources) or set())
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[Dead()], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert "gmail: failed" in text_of(app, "#activity")
            await pilot.click("#reconnect")
            for _ in range(100):
                await asyncio.sleep(0.05)
                await pilot.pause()
                if "gmail: ok" in text_of(app, "#activity"):
                    break
            else:
                raise AssertionError("resync after reconnect never happened")
            assert connected == [("gmail", "calendar", "drive")]

    asyncio.run(go())


def test_declining_reconnect_does_not_resync(tmp_path, monkeypatch):
    from archie.connectors import google_auth

    class Dead:
        name = "gmail"

        async def sync(self, sctx, cursor):
            raise google_auth.NeedsAuth(f"Google access expired: run `{google_auth.RECONNECT_HINT}`")

    connected = []
    monkeypatch.setattr(google_auth, "connect", lambda client, sources: connected.append(sources) or set())
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[Dead()], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            await pilot.click("#dismiss")
            await pilot.pause()
            assert connected == []
            assert "gmail: failed" in text_of(app, "#activity")

    asyncio.run(go())


def test_slow_answer_times_out_with_a_message(tmp_path, monkeypatch):
    import time as _time

    import archie.tui.app as tui

    monkeypatch.setattr(tui, "ASK_TIMEOUT", 0.3)
    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q, progress=None: _time.sleep(2))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.click("#question")
            await pilot.press(*"slow", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            assert "took too long" in text_of(app, ".answer")

    asyncio.run(go())


def test_gemma_backend_never_times_out(tmp_path, monkeypatch):
    import time as _time

    import archie.tui.app as tui
    from archie.ask.answer import Answer
    from archie.llm.backend import GemmaBackend

    monkeypatch.setattr(tui, "ASK_TIMEOUT", 0.1)  # would fire almost immediately for any other backend
    monkeypatch.setattr("archie.ask.pipeline.ask",
                        lambda ctx, q, progress=None: _time.sleep(0.3) or Answer(plain="slow but fine"))
    ctx = make_ctx(tmp_path, GemmaBackend({}))

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.click("#question")
            await pilot.press(*"slow", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            assert "took too long" not in text_of(app, ".answer")

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
            assert pane.border_subtitle == "Gemini: $0.00 of $15 this month ($0.00 this session)"
            ctx.backend.budget.record("gemini-3.7-flash", "fast", 28_000, 0, 0)
            app.refresh_spend()
            await pilot.pause()
            assert pane.border_subtitle == "Gemini: $0.02 of $15 this month ($0.02 this session)"

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
                "Gemini: $0.00 of $15 this month ($0.00 this session) · Google: $1.50, out of step"

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


def test_earlier_answers_stay_in_the_ask_pane_to_scroll_back_to(tmp_path, monkeypatch):
    from archie.ask.answer import Answer

    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q, progress=None: Answer(plain=f"Answer to {q}. " + "More. " * 200))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            for q in ("first", "second"):
                await pilot.click("#question")
                await pilot.press(*q, "enter")
                await app.ask_done.wait()
                await pilot.pause()
            entries = [str(e.render()) for e in app.query(".answer")]
            assert len(entries) == 2 and "Answer to first" in entries[0] and "Answer to second" in entries[1]
            assert len(app.query(".exchange")) == 2
            asked = app.query(".asked")
            assert [str(a.render()).strip() for a in asked] == ["You asked: first", "You asked: second"]
            assert asked.last().styles.background != app.query(".answer").last().styles.background
            assert entries[1].startswith("Answer to second")  # the question isn't repeated in the answer
            assert not app.query("#hint")
            pane = app.query_one("#answer-scroll")
            assert pane.max_scroll_y > 0 and pane.scroll_y > 0  # scrolled down to the newest answer
            assert app.focused is app.query_one("#question")
            before = pane.scroll_y
            await pilot.press("pageup")
            await pilot.pause(0.5)
            assert pane.scroll_y < before
            app.action_copy_answer()
            assert "Answer to second" in app.clipboard

    asyncio.run(go())


def test_launch_shows_the_last_few_asks(tmp_path):
    from datetime import datetime, timedelta, timezone

    from archie.ask import conversation

    ctx = make_ctx(tmp_path)
    t0 = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    conversation.append(ctx.home, {"ts": t0.isoformat(), "said": "oldest", "summary": "Saved before shown existed."})
    for i in range(1, 7):
        conversation.append(ctx.home, {"ts": (t0 + timedelta(minutes=i)).isoformat(), "said": f"q{i}",
                                       "summary": "short", "shown": f"Full answer {i}\n\nSources:\n[1] Email"})

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            asked = [str(a.render()) for a in app.query(".asked")]
            assert asked == [f"You asked: q{i}" for i in range(2, 7)]
            assert str(app.query(".answer").last().render()) == "Full answer 6\n\nSources:\n[1] Email"
            assert not app.query("#hint")
            pane = app.query_one("#answer-scroll")
            assert pane.scroll_y == pane.max_scroll_y > 0
            assert app.focused is app.query_one("#question")

    asyncio.run(go())


def test_an_ask_saved_without_its_full_answer_shows_when_and_the_summary(tmp_path):
    from datetime import datetime, timezone

    from archie.ask import conversation
    from archie.store.times import stamp

    ctx = make_ctx(tmp_path)
    at = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    conversation.append(ctx.home, {"ts": at.isoformat(), "said": "who is priya", "summary": "Priya is the PM. [1]"})

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            assert text_of(app, ".answer") == f"{stamp(at)}\n\nPriya is the PM. [1]"

    asyncio.run(go())


def test_earlier_sync_reports_stay_in_the_sync_pane(tmp_path):
    ctx = make_ctx(tmp_path)
    conn = Counting()

    async def go():
        app = ArchieApp(ctx, connectors=[conn], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            app.sync_done.clear()
            await app.sync_cycle()
            await pilot.pause()
            earlier = [str(e.render()) for e in app.query(".earlier-sync")]
            assert len(earlier) == 1 and "gmail: ok" in earlier[0]
            assert "gmail: ok" in text_of(app, "#activity")

    asyncio.run(go())


def test_today_pane_scrolls(tmp_path):
    ctx = make_ctx(tmp_path)
    long = "\n".join(f"item {i}" for i in range(100))

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], feed=lambda c: long, ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            pane = app.query_one("#feed-scroll")
            assert pane.border_title == "Today" and pane.max_scroll_y > 0

    asyncio.run(go())


def test_selecting_text_with_the_mouse_copies_it(tmp_path, monkeypatch):
    from textual import events
    from textual.selection import Selection

    import archie.tui.app as tui

    copied = []
    monkeypatch.setattr(tui, "_pbcopy", lambda text: copied.append(text))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], feed=lambda c: "Standup at 10 AM", ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            app.screen.selections = {app.query_one("#feed"): Selection(None, None)}
            app.screen.post_message(events.TextSelected())
            await pilot.pause()

    asyncio.run(go())
    assert copied == ["Standup at 10 AM"]


def test_pasting_goes_into_the_question_box(tmp_path):
    from textual import events

    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.click("#feed")
            app.post_message(events.Paste("who is priya"))
            await pilot.pause()
            assert app.query_one("#question").value == "who is priya"

    asyncio.run(go())


def screen_text(widget):
    return "\n".join(line.text for line in widget.render_lines(widget.region.reset_offset)).rstrip()


def test_a_source_excerpt_in_markdown_is_drawn_as_markdown(tmp_path, monkeypatch):
    from archie.ask.answer import Answer

    md = "## My notes\n- I will meet with _Workpersontwo_ next week"
    text = f"[1] Workpersontwo (dossier)\n“I will meet with Workpersontwo next week”\n\n{md}\n\npeople/workpersontwo.md"
    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q, progress=None: Answer(plain=text, markdown=md))
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test(size=(160, 50)) as pilot:
            await app.sync_done.wait()
            await pilot.click("#question")
            await pilot.press(*"show 1", "enter")
            await app.ask_done.wait()
            await pilot.pause()
            drawn = screen_text(app.query(".answer").last())
            assert "My notes" in drawn and "• I will meet with Workpersontwo next week" in drawn
            assert "##" not in drawn and "_Workpersontwo_" not in drawn
            assert drawn.rstrip().endswith("people/workpersontwo.md")
            app.action_copy_answer()
            assert md in app.clipboard

    asyncio.run(go())

    from archie.ask import conversation

    conversation.append(ctx.home, {"ts": "2026-10-04T16:00:00+00:00", "said": "show 1", "shown": text, "markdown": md})

    async def relaunch():
        app = ArchieApp(ctx, connectors=[], derivers=[], ticker=lambda c: [])
        async with app.run_test(size=(160, 50)) as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert "##" not in screen_text(app.query(".answer").last())

    asyncio.run(relaunch())


def test_today_pane_refreshes_after_an_answer(tmp_path, monkeypatch):
    from archie.ask.answer import Answer

    state = {"feed": "before"}
    monkeypatch.setattr("archie.ask.pipeline.ask", lambda ctx, q, progress=None: (state.update(feed="after"), Answer(plain="Done."))[1])
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


def test_sync_report_shows_what_post_index_steps_say(tmp_path):
    ctx = make_ctx(tmp_path)

    async def go():
        app = ArchieApp(ctx, connectors=[Counting()], derivers=[], ticker=lambda c: [],
                        post_index=[lambda c: ["Re-applied 1 thing you told me earlier: Acorn"]])
        async with app.run_test() as pilot:
            await app.sync_done.wait()
            await pilot.pause()
            assert "Re-applied 1 thing you told me earlier: Acorn" in text_of(app, "#activity")

    asyncio.run(go())
