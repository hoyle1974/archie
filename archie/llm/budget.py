"""Archie's own monthly spending limit for the model (llm.monthly_budget_usd).

Every call's token counts, as Gemini reports them, are appended to logs/llm_usage.jsonl with
their cost. Before each call the month's total (UTC calendar month) is added up, and once it
reaches the limit no more calls are made until the 1st. A call in flight can overshoot by at
most that one call. Prices are per million tokens, newest first with the date they apply
from; output includes thinking tokens. A model with no known price is counted at the highest
listed rate so the estimate errs high.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Callable

from archie.store.home import Home

PRICES = {  # model: [(from date, input $/1M, output $/1M), ...] newest first
    "gemini-3.6-flash": [("2027-01-01", 1.50, 7.50), ("", 0.75, 3.75)],
    "gemini-3.7-flash": [("2027-01-01", 1.50, 7.50), ("", 0.75, 3.75)],
    "gemini-3.8-flash": [("2027-01-01", 1.50, 7.50), ("", 0.75, 3.75)],
    "gemini-3.1-pro-preview": [("", 2.00, 12.00)],
}
UNKNOWN = (4.00, 18.00)
LOG = "logs/llm_usage.jsonl"


def cost_usd(model: str, prompt_tokens: int, output_tokens: int, when: datetime) -> float:
    day = when.date().isoformat()
    rate_in, rate_out = next(((i, o) for start, i, o in PRICES.get(model, []) if start <= day), UNKNOWN)
    return (prompt_tokens * rate_in + output_tokens * rate_out) / 1_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Budget:
    def __init__(self, home: Home, limit: float, clock: Callable[[], datetime] = _now):
        self.home, self.limit, self.clock = home, float(limit), clock
        self.lock = threading.Lock()
        self._cache: tuple = (None, 0.0)

    @property
    def path(self):
        return self.home.root / LOG

    def spent(self) -> float:
        now = self.clock().astimezone(timezone.utc)
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return 0.0
        key = (st.st_mtime_ns, st.st_size, now.year, now.month)
        if self._cache[0] == key:
            return self._cache[1]
        total = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"]).astimezone(timezone.utc)
            except (ValueError, KeyError, TypeError):
                continue
            if (ts.year, ts.month) == (now.year, now.month):
                total += float(entry.get("usd") or 0)
        self._cache = (key, total)
        return total

    def summary(self) -> str:
        spent = self.spent()
        amount = f"${spent:.2f}" if spent >= 1 else f"{spent * 100:.1f}".rstrip("0").rstrip(".") + "¢"
        line = f"Gemini: {amount} of ${self.limit:g} this month"
        return line if spent < self.limit else f"{line}: paused until {self.resets()}"

    def resets(self) -> str:
        now = self.clock().astimezone(timezone.utc)
        nxt = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)
        return f"{nxt:%b} 1"

    def check(self) -> None:
        from archie.llm.backend import LLMError

        if self.spent() >= self.limit:
            raise LLMError(f"Archie's monthly Gemini budget (${self.limit:g}) is used up; it resets on "
                           f"{self.resets()}. Raise llm.monthly_budget_usd in config.yaml to continue sooner")

    def record(self, model: str, tier: str, prompt_tokens: int, output_tokens: int, thinking_tokens: int) -> None:
        now = self.clock()
        usd = cost_usd(model, prompt_tokens, output_tokens + thinking_tokens, now)
        entry = {"ts": now.isoformat(), "model": model, "tier": tier, "in": prompt_tokens, "out": output_tokens,
                 "thinking": thinking_tokens, "usd": round(usd, 6)}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
