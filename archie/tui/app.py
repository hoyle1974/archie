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

HINT = 'Ask anything, e.g. "prep me for my next meeting" or "what do I owe people?"'


def default_feed(ctx: Ctx) -> str:
    from archie.tui.feed import build_feed

    return build_feed(ctx)


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
    BINDINGS = [("ctrl+r", "sync_now", "Sync now"), ("ctrl+q", "quit", "Quit")]

    def __init__(self, ctx: Ctx, connectors: list, derivers: list, feed: Callable[[Ctx], str] = default_feed):
        super().__init__()
        self.ctx = ctx
        self.connectors = connectors
        self.derivers = derivers
        self.feed_builder = feed
        self.sync_done = asyncio.Event()
        self.ask_done = asyncio.Event()
        self._syncing = asyncio.Lock()

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                yield Static("Loading…", id="feed")
                yield Static("Starting up…", id="activity")
            with Vertical(id="right"):
                with VerticalScroll(id="answer-scroll"):
                    yield Static(HINT, id="answer")
                yield Input(placeholder="Ask Archie…", id="question")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#feed").border_title = "Today"
        self.query_one("#activity").border_title = "Sync"
        self.query_one("#answer-scroll").border_title = "Ask"
        self.query_one("#question").focus()
        self.run_worker(self.sync_cycle(), exclusive=False)
        minutes = self.ctx.config["sync"]["interval_minutes"]
        self.set_interval(minutes * 60, lambda: self.run_worker(self.sync_cycle()))

    async def action_sync_now(self) -> None:
        self.run_worker(self.sync_cycle())

    async def sync_cycle(self) -> None:
        from archie.sync import run_cycle

        if self._syncing.locked():
            return
        async with self._syncing:
            activity = self.query_one("#activity", Static)
            activity.update("Syncing…")
            self.ctx.now = datetime.now(timezone.utc)
            try:
                report = await run_cycle(self.ctx, self.connectors, self.derivers)
                stamp = datetime.now().strftime("%-I:%M %p")
                lines = [f"Last sync {stamp}"]
                lines += [f"{n}: ok, {r.written} updated" if r.ok else f"{n}: failed: {r.error[:120]}"
                          for n, r in report.items()]
                if not report:
                    lines.append("No sources switched on (see config.yaml).")
                activity.update("\n".join(lines))
            except Exception as exc:  # the loop must survive anything
                activity.update(f"Sync failed: {exc}")
            await self.refresh_feed()
            self.sync_done.set()

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
        try:
            answer = await asyncio.to_thread(ask, self.ctx, question)
            out.update(f"> {question}\n\n{render(answer, sources=True)}")
        except Exception as exc:
            out.update(f"> {question}\n\nSomething went wrong: {exc}")
        self.ask_done.set()


def run_tui() -> int:
    from archie.cli import build_ctx
    from archie.connectors.registry import enabled_connectors
    from archie.derive.registry import all_derivers
    from archie.store.home import Home

    ctx = build_ctx(Home.default())
    ArchieApp(ctx, enabled_connectors(ctx.config), all_derivers()).run()
    return 0
