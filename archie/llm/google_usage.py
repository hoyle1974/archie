"""Google's own count of this month's Gemini tokens, checked against Archie's log on every sync.

Cloud Monitoring on the project in llm.google_project holds the counts the AI Studio usage page
shows: output tokens (thinking included) per model, and input tokens per model in a quota metric
whose name follows the account's usage tier (paid_tier_2, …), so every paid tier's metric is
added up. Both sides are priced with budget.PRICES and compared for the UTC calendar month up to
a few minutes ago, because Google's figures arrive about 2½ minutes late. The result goes to
state/google_usage.yaml. Read-only, with Archie's Google sign-in (the monitoring.read scope).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable

import yaml

from archie.llm.budget import PRICES, Budget, cost_usd, money
from archie.store.files import atomic_write
from archie.store.home import Home

API = "https://monitoring.googleapis.com/v3"
OUTPUT = "generativelanguage.googleapis.com/generate_content_usage_output_token_count"
INPUT = re.compile(r"generativelanguage\.googleapis\.com/quota/"
                   r"generate_content_paid_tier(_\d+)?_input_token_count/usage")
STATE = "state/google_usage.yaml"
LAG = timedelta(minutes=5)
WARN_USD = 1.0

Get = Callable[[str, dict], dict]


def _pages(get: Get, path: str, params: dict, key: str):
    params = dict(params)
    while True:
        page = get(path, params)
        yield from page.get(key) or []
        if not page.get("nextPageToken"):
            return
        params["pageToken"] = page["nextPageToken"]


def google_tokens(project: str, start: datetime, end: datetime, get: Get) -> dict[str, dict[str, int]]:
    """{model: {"in": tokens, "out": tokens}} as Google counted them between start and end."""
    root = f"projects/{project}"
    tier_filter = 'metric.type = starts_with("generativelanguage.googleapis.com/quota/generate_content_paid_tier")'
    inputs = [d["type"] for d in _pages(get, f"{root}/metricDescriptors", {"filter": tier_filter}, "metricDescriptors")
              if INPUT.fullmatch(d.get("type", ""))]
    window = {
        "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregation.alignmentPeriod": f"{max(60, int((end - start).total_seconds()))}s",
        "aggregation.perSeriesAligner": "ALIGN_SUM",
        "aggregation.crossSeriesReducer": "REDUCE_SUM",
        "aggregation.groupByFields": "metric.labels.model",
    }
    out: dict[str, dict[str, int]] = {}
    for metric, side in [(m, "in") for m in inputs] + [(OUTPUT, "out")]:
        params = {**window, "filter": f'metric.type="{metric}"'}
        for s in _pages(get, f"{root}/timeSeries", params, "timeSeries"):
            tally = out.setdefault(s["metric"].get("labels", {}).get("model", ""), {"in": 0, "out": 0})
            tally[side] += sum(int(p["value"].get("int64Value") or 0) for p in s.get("points", []))
    return out


def priced(model: str) -> str:
    """Google drops the -preview suffix from model names; match it to the priced name."""
    if model in PRICES:
        return model
    return next((name for name in PRICES if name.startswith(f"{model}-")), model)


def _get(project: str) -> Get:
    from google.auth.transport.requests import AuthorizedSession

    from archie.connectors.google_auth import credentials

    session = AuthorizedSession(credentials("monitoring").with_quota_project(project))

    def get(path: str, params: dict) -> dict:
        resp = session.get(f"{API}/{path}", params=params, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(resp.json().get("error", {}).get("message") or f"HTTP {resp.status_code}")
        return resp.json()

    return get


def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def check(home: Home, project: str, now: datetime | None = None, get: Get | None = None) -> dict:
    """Compare Google's count with Archie's log, save it, and return it. Never raises."""
    from archie.sync import friendly

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start, end = _month_start(now), max(_month_start(now), now - LAG)
    entry = {"month": f"{now:%Y-%m}", "checked": now.isoformat(timespec="seconds"),
             "as_of": end.isoformat(timespec="seconds"),
             "archie_usd": round(Budget(home, 0).spent_between(start, end), 6)}
    try:
        tokens = google_tokens(project, start, end, get or _get(project)) if end > start else {}
    except Exception as exc:  # a failed check must never stop a sync
        entry["error"] = friendly(str(exc) or type(exc).__name__)[:300]
    else:
        entry["tokens"] = tokens
        entry["google_usd"] = round(sum(cost_usd(priced(m), t["in"], t["out"], end) for m, t in tokens.items()), 6)
    atomic_write(home / STATE, yaml.safe_dump(entry, sort_keys=False, allow_unicode=True))
    return entry


def load(home: Home, now: datetime | None = None) -> dict | None:
    """This month's last check, or None."""
    path = home / STATE
    if not path.exists():
        return None
    try:
        entry = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(entry, dict):
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return entry if entry.get("month") == f"{now:%Y-%m}" else None


def warning(entry: dict) -> str | None:
    if "google_usd" not in entry:
        return None
    google, archie = entry["google_usd"], entry["archie_usd"]
    gap = google - archie
    if abs(gap) <= WARN_USD:
        return None
    more = "more" if gap > 0 else "less"
    return (f"Google counts {money(abs(gap))} {more} Gemini use this month than Archie logged "
            f"({money(google)} vs {money(archie)})")


def status_line(entry: dict) -> str:
    if "error" in entry:
        return f"Google's token count: couldn't check ({entry['error']})"
    warn = warning(entry)
    if warn:
        return f"Warning: {warn}"
    return f"Google's count this month: {money(entry['google_usd'])} (Archie logged {money(entry['archie_usd'])})"


def subtitle(home: Home, now: datetime | None = None) -> str:
    """Added after the spend line in the TUI's Ask pane; empty when there's nothing to show."""
    entry = load(home, now)
    if not entry or "google_usd" not in entry:
        return ""
    return f" · Google: {money(entry['google_usd'])}{', out of step' if warning(entry) else ''}"
