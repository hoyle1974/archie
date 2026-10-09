"""The Archie TUI. Keep it open in a window: it syncs on launch (catch-up), then every
`sync.interval_minutes`, and refreshes the Feed after each cycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from archie.ask.context import Ctx
from archie.ask.render import render
from archie.llm.backend import LLMError

ASK_TIMEOUT = 180  # seconds before the Ask pane gives up and frees itself
SPEND_REFRESH_S = 3
KEEP_ANSWERS = 50
RESTORE_ASKS = 5
KEEP_SYNC_REPORTS = 20
HINT = 'Ask anything, e.g. "prep me for my next meeting" or "what do I owe people?"'


class Pane(VerticalScroll):
    """Scrolls with the mouse wheel but never takes focus, so the cursor stays in the question box."""

    can_focus = False


class AnswerText(Static):
    """An answer as plain text, except a source excerpt in it (`markdown`), which is drawn as
    Markdown: headings, lists and emphasis instead of #, - and _."""

    def __init__(self, text: str, markdown: str | None = None):
        super().__init__(classes="answer", markup=False)
        self.say(text, markdown)

    def say(self, text: str, markdown: str | None = None) -> None:
        self.text = text
        if not markdown or markdown not in text:
            self.update(text)
            return
        from rich.console import Group
        from rich.markdown import Markdown
        from rich.text import Text

        before, _, after = text.partition(markdown)
        self.update(Group(Text(before.rstrip("\n") + "\n"), Markdown(markdown), Text("\n" + after.lstrip("\n"))))


def exchange(question: str, text: str, markdown: str | None = None) -> tuple[Vertical, AnswerText]:
    """One ask in the Ask pane: the question on its own band, the answer below it."""
    out = AnswerText(text, markdown)
    return Vertical(Static(f"You asked: {question}", classes="asked", markup=False), out, classes="exchange"), out


def _pbcopy(text: str) -> None:
    import subprocess

    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def log_error(ctx: Ctx, where: str) -> None:
    """Append the current exception's traceback to logs/errors.log (local, gitignored)."""
    import traceback

    try:
        path = ctx.home / "logs/errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now(timezone.utc).isoformat(timespec='seconds')} {where}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def default_feed(ctx: Ctx) -> str:
    from archie.tui.feed import build_feed

    return build_feed(ctx)


def default_ticker(ctx: Ctx) -> list[str]:
    from archie.briefings.schedule import tick

    return tick(ctx)


class ArchieApp(App):
    TITLE = "Archie"
    CSS = """
    #left { width: 45%; }
    #feed-scroll { height: 1fr; border: round $accent; padding: 0 1; }
    #activity-scroll { height: 8; border: round $panel; padding: 0 1; }
    #activity, .earlier-sync { color: $text-muted; }
    .earlier-sync { border-bottom: hkey $panel; }
    #right { width: 55%; }
    #answer-scroll { height: 1fr; border: round $accent; padding: 0 1; }
    .exchange { height: auto; margin-top: 1; padding-top: 1; border-top: heavy $accent; }
    .exchange:first-child { margin-top: 0; padding-top: 0; border-top: none; }
    .asked { background: $accent 30%; color: $text; text-style: bold; padding: 0 1; }
    .answer { padding-top: 1; }
    #question { dock: bottom; }
    """
    BINDINGS = [("ctrl+y", "copy_answer", "Copy answer"), ("ctrl+r", "sync_now", "Sync now"),
                Binding("pageup", "scroll_answers(-1)", "Earlier", priority=True),
                Binding("pagedown", "scroll_answers(1)", "Later", priority=True),
                ("ctrl+q", "quit", "Quit")]

    def __init__(self, ctx: Ctx, connectors: list, derivers: list, feed: Callable[[Ctx], str] = default_feed,
                 ticker: Callable[[Ctx], list[str]] = default_ticker, post_index: list | None = None):
        super().__init__()
        self.ctx = ctx
        self.post_index = post_index or []
        self.ticker = ticker
        self.connectors = connectors
        self.derivers = derivers
        self.feed_builder = feed
        self.sync_done = asyncio.Event()
        self.ask_done = asyncio.Event()
        self._syncing = asyncio.Lock()
        self._last_report: str | None = None  # the finished sync report #activity shows, if any

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                with Pane(id="feed-scroll"):
                    yield Static("Loading…", id="feed", markup=False)
                with Pane(id="activity-scroll"):
                    yield Static("Starting up…", id="activity", markup=False)
            with Vertical(id="right"):
                with Pane(id="answer-scroll"):
                    earlier = self.earlier_asks()
                    for said, text, markdown in earlier:
                        yield exchange(said, text, markdown)[0]
                    if not earlier:
                        yield Static(HINT, id="hint", markup=False)
                yield Input(placeholder="Ask Archie…", id="question")
        yield Footer()

    def earlier_asks(self) -> list[tuple[str, str, str | None]]:
        """The last few exchanges (from this window, other windows or `archie ask`), oldest first."""
        from archie.ask import conversation

        try:
            entries = conversation.load(self.ctx.home)[-RESTORE_ASKS:]
        except OSError:
            return []
        return [(e.get("said") or "", conversation.shown(e), e.get("markdown")) for e in entries]

    async def on_unmount(self) -> None:
        self.writer.release()

    async def on_mount(self) -> None:
        from archie.store.lock import WriterLock

        self.writer = WriterLock(self.ctx.home.root)
        self.is_writer = self.writer.acquire()
        self.query_one("#feed-scroll").border_title = "Today"
        self.query_one("#activity-scroll").border_title = "Sync"
        self.query_one("#answer-scroll").border_title = "Ask"
        self.query_one("#question").focus()
        blocks = self.query(".exchange")
        if blocks:
            self.show_top_of(blocks.last())
        self.refresh_spend()
        self.set_interval(SPEND_REFRESH_S, self.refresh_spend)
        self.run_worker(self.sync_cycle(), exclusive=False)
        minutes = self.ctx.config["sync"]["interval_minutes"]
        self.set_interval(minutes * 60, lambda: self.run_worker(self.sync_cycle()))
        self.set_interval(60, lambda: self.run_worker(self.briefing_tick()))

    def refresh_spend(self) -> None:
        """Gemini spend this month in the Ask pane's border. Polled so calls from background
        sync and from `archie ask` in other terminals show up too; re-reads only on change."""
        budget = getattr(self.ctx.backend, "budget", None)
        if budget is None:
            return
        from archie.llm import google_usage
        from archie.llm.budget import money

        try:
            text = f"{budget.summary()} ({money(budget.session_usd)} this session){google_usage.subtitle(self.ctx.home)}"
        except (OSError, ValueError):
            return
        self.query_one("#answer-scroll").border_subtitle = text

    def google_usage_line(self) -> str | None:
        """After a sync: Google's own Gemini token count against Archie's log, with a toast if they disagree."""
        from archie.llm import google_usage

        if not self.ctx.config["llm"].get("google_project"):
            return None
        try:
            entry = google_usage.load(self.ctx.home)
        except (OSError, ValueError):
            return None
        if not entry:
            return None
        warn = google_usage.warning(entry)
        if warn:
            self.notify(warn, severity="warning", timeout=30)
        return google_usage.status_line(entry)

    def copy_to_clipboard(self, text: str) -> None:
        """Textual copies with OSC 52, which macOS Terminal ignores; also use pbcopy."""
        super().copy_to_clipboard(text)
        _pbcopy(text)

    def on_text_selected(self, event: events.TextSelected) -> None:
        """Copy as soon as a mouse drag ends: iTerm2 and Terminal keep Cmd+C for their own selection."""
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.notify("Copied. Paste with Cmd+V.", timeout=2)

    def action_copy_answer(self) -> None:
        entries = self.query(AnswerText)
        text = entries.last().text if entries else HINT
        self.copy_to_clipboard(text)
        self.notify("Copied the answer.", timeout=2)

    def action_scroll_answers(self, direction: int) -> None:
        pane = self.query_one("#answer-scroll", Pane)
        pane.scroll_page_down() if direction > 0 else pane.scroll_page_up()

    def show_top_of(self, widget: Widget) -> None:
        widget.parent.call_after_refresh(widget.parent.scroll_to_widget, widget, top=True, animate=False)

    async def action_sync_now(self) -> None:
        self.run_worker(self.sync_cycle())

    async def start_sync_report(self, text: str) -> None:
        """Move the last finished report up into the Sync pane's history, then show `text` below it."""
        activity = self.query_one("#activity", Static)
        if self._last_report:
            pane = self.query_one("#activity-scroll", Pane)
            await pane.mount(Static(self._last_report, classes="earlier-sync", markup=False), before=activity)
            earlier = pane.query(".earlier-sync")
            for old in list(earlier)[:-KEEP_SYNC_REPORTS]:
                await old.remove()
            self._last_report = None
        activity.update(text)
        self.show_top_of(activity)

    def finish_sync_report(self, text: str) -> None:
        activity = self.query_one("#activity", Static)
        activity.update(text)
        self._last_report = text
        self.show_top_of(activity)

    async def sync_cycle(self) -> None:
        from archie.sync import run_cycle

        if self._syncing.locked():
            return
        if not self.is_writer:  # another Archie window owns syncing; this one only answers
            self.is_writer = self.writer.acquire()
            if not self.is_writer:
                self.query_one("#activity", Static).update("Another Archie window is syncing; this one only answers.")
                await self.refresh_feed()
                self.sync_done.set()
                return
        async with self._syncing:
            activity = self.query_one("#activity", Static)
            await self.start_sync_report("Syncing…")
            self.ctx.now = datetime.now(timezone.utc)
            try:
                notes: list[str] = []
                report = await run_cycle(self.ctx, self.connectors, self.derivers, post_index=self.post_index,
                                         on_progress=activity.update, notes=notes)
                stamp = datetime.now().strftime("%-I:%M %p")
                lines = [f"Last sync {stamp}"]
                google = self.google_usage_line()
                if google:
                    lines.append(google)
                lines += [f"{n}: ok, {r.written} updated" if r.ok else f"{n}: failed: {r.error[:220]}"
                          for n, r in report.items()]
                if not report:
                    lines.append("No sources switched on (see config.yaml).")
                lines += notes
                self.finish_sync_report("\n".join(lines))
                self.refresh_spend()
            except Exception as exc:  # the loop must survive anything
                log_error(self.ctx, "sync")
                stamp = datetime.now().strftime("%-I:%M %p")
                self.finish_sync_report(f"Sync failed at {stamp}: {exc} (details in logs/errors.log)")
            await self.briefing_tick(refresh=False)
            await self.refresh_feed()
            self.sync_done.set()

    async def briefing_tick(self, refresh: bool = True) -> None:
        if not getattr(self, "is_writer", False):
            return  # briefings are written by the window that owns syncing
        self.ctx.now = datetime.now(timezone.utc)
        try:
            built = await asyncio.to_thread(self.ticker, self.ctx)
        except Exception as exc:  # never let briefings kill the app
            self.query_one("#activity", Static).update(f"Briefing failed: {exc}")
            return
        if refresh:  # every minute: meetings that ended drop off, the next one moves up
            await self.refresh_feed()

    async def refresh_feed(self) -> None:
        try:
            text = await asyncio.to_thread(self.feed_builder, self.ctx)
        except Exception as exc:
            text = f"Couldn't build today's feed: {exc}"
        self.query_one("#feed", Static).update(text)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if not question:
            return
        event.input.value = ""
        pane = self.query_one("#answer-scroll", Pane)
        await pane.query("#hint").remove()
        block, out = exchange(question, "Thinking…")
        await pane.mount(block)
        for old in list(pane.query(".exchange"))[:-KEEP_ANSWERS]:
            await old.remove()
        self.show_top_of(block)
        self.ask_done.clear()
        self.run_worker(self._answer(question, block, out))

    async def _answer(self, question: str, block: Vertical, out: AnswerText) -> None:
        from archie.ask.pipeline import ask

        self.ctx.now = datetime.now(timezone.utc)
        started = asyncio.get_running_loop().time()

        latest, done = ["Still working…"], [False]

        def tick() -> None:
            waited = int(asyncio.get_running_loop().time() - started)
            if waited >= 20 and not done[0]:
                out.say(f"{latest[0]} ({waited}s)")

        def show(line: str) -> None:
            if not done[0]:  # a worker left running after the timeout mustn't cover the final message
                out.say(line)

        def progress(line: str) -> None:  # called from the worker thread while Archie digs further
            latest[0] = line
            self.call_from_thread(show, line)

        def finish(text: str, markdown: str | None = None) -> None:
            done[0] = True
            out.say(text, markdown)

        timer = self.set_interval(5, tick)
        try:
            answer = await asyncio.wait_for(asyncio.to_thread(ask, self.ctx, question, progress), ASK_TIMEOUT)
            finish(render(answer, sources=True, stamp=True), answer.markdown)
        except asyncio.TimeoutError:
            finish("That took too long, so I stopped waiting. Try asking again.")
        except LLMError as exc:
            finish(f"Archie couldn't write an answer: {exc}")
        except Exception as exc:
            log_error(self.ctx, f"ask: {question}")
            finish(f"Something went wrong: {exc} (details in logs/errors.log)")
        finally:
            timer.stop()
        self.show_top_of(block)
        await self.refresh_feed()  # answers can close loops, add notes or fix meetings
        self.ask_done.set()


def run_tui() -> int:
    from archie.cli import build_ctx
    from archie.connectors.registry import enabled_connectors
    from archie.derive.registry import all_derivers
    from archie.store.home import Home

    ctx = build_ctx(Home.default())
    from archie.derive.registry import post_index_steps

    ArchieApp(ctx, enabled_connectors(ctx.config), all_derivers(), post_index=post_index_steps()).run()
    return 0
