"""The Archie TUI. Keep it open in a window: it syncs on launch (catch-up), then every
`sync.interval_minutes`, and refreshes the Feed after each cycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static

from archie.ask.context import Ctx
from archie.ask.render import render

ASK_TIMEOUT = 180  # seconds before the Ask pane gives up and frees itself
HINT = 'Ask anything, e.g. "prep me for my next meeting" or "what do I owe people?"'


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
    #feed { height: 1fr; border: round $accent; padding: 0 1; }
    #activity { height: 8; border: round $panel; padding: 0 1; color: $text-muted; }
    #right { width: 55%; }
    #answer-scroll { height: 1fr; border: round $accent; padding: 0 1; }
    #question { dock: bottom; }
    """
    BINDINGS = [("ctrl+y", "copy_answer", "Copy answer"), ("ctrl+r", "sync_now", "Sync now"),
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

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                yield Static("Loading…", id="feed", markup=False)
                yield Static("Starting up…", id="activity", markup=False)
            with Vertical(id="right"):
                with VerticalScroll(id="answer-scroll"):
                    yield Static(HINT, id="answer", markup=False)
                yield Input(placeholder="Ask Archie…", id="question")
        yield Footer()

    async def on_unmount(self) -> None:
        self.writer.release()

    async def on_mount(self) -> None:
        from archie.store.lock import WriterLock

        self.writer = WriterLock(self.ctx.home.root)
        self.is_writer = self.writer.acquire()
        self.query_one("#feed").border_title = "Today"
        self.query_one("#activity").border_title = "Sync"
        self.query_one("#answer-scroll").border_title = "Ask"
        self.query_one("#question").focus()
        self.run_worker(self.sync_cycle(), exclusive=False)
        minutes = self.ctx.config["sync"]["interval_minutes"]
        self.set_interval(minutes * 60, lambda: self.run_worker(self.sync_cycle()))
        self.set_interval(60, lambda: self.run_worker(self.briefing_tick()))

    def copy_to_clipboard(self, text: str) -> None:
        """Textual copies with OSC 52, which macOS Terminal ignores; also use pbcopy."""
        super().copy_to_clipboard(text)
        _pbcopy(text)

    def action_copy_answer(self) -> None:
        text = str(self.query_one("#answer", Static).render())
        self.copy_to_clipboard(text)
        self.notify("Copied the answer.", timeout=2)

    async def action_sync_now(self) -> None:
        self.run_worker(self.sync_cycle())

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
            activity.update("Syncing…")
            self.ctx.now = datetime.now(timezone.utc)
            try:
                report = await run_cycle(self.ctx, self.connectors, self.derivers, post_index=self.post_index)
                stamp = datetime.now().strftime("%-I:%M %p")
                lines = [f"Last sync {stamp}"]
                lines += [f"{n}: ok, {r.written} updated" if r.ok else f"{n}: failed: {r.error[:220]}"
                          for n, r in report.items()]
                if not report:
                    lines.append("No sources switched on (see config.yaml).")
                activity.update("\n".join(lines))
            except Exception as exc:  # the loop must survive anything
                log_error(self.ctx, "sync")
                activity.update(f"Sync failed: {exc} (details in logs/errors.log)")
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
        if built and refresh:
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
        out = self.query_one("#answer", Static)
        out.update(f"> {question}\n\nThinking…")
        self.ask_done.clear()
        self.run_worker(self._answer(question))

    async def _answer(self, question: str) -> None:
        from archie.ask.pipeline import ask

        out = self.query_one("#answer", Static)
        self.ctx.now = datetime.now(timezone.utc)
        started = asyncio.get_running_loop().time()

        def tick() -> None:
            waited = int(asyncio.get_running_loop().time() - started)
            if waited >= 20 and not self.ask_done.is_set():
                out.update(f"> {question}\n\nStill working… ({waited}s)")

        timer = self.set_interval(5, tick)
        try:
            answer = await asyncio.wait_for(asyncio.to_thread(ask, self.ctx, question), ASK_TIMEOUT)
            out.update(f"> {question}\n\n{render(answer, sources=True)}")
        except asyncio.TimeoutError:
            out.update(f"> {question}\n\nThat took too long, so I stopped waiting. Try asking again.")
        except Exception as exc:
            log_error(self.ctx, f"ask: {question}")
            out.update(f"> {question}\n\nSomething went wrong: {exc} (details in logs/errors.log)")
        finally:
            timer.stop()
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
