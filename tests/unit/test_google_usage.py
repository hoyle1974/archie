import asyncio
import re
from datetime import datetime, timedelta, timezone

import pytest

from archie import doctor
from archie.llm import google_usage
from archie.llm.budget import Budget
from archie.store.home import init_home
from archie.sync import run_cycle
from tests.support.fixtures import make_ctx

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
FLASH = "gemini-3.7-flash"
OUT = google_usage.OUTPUT
TIER2 = "generativelanguage.googleapis.com/quota/generate_content_paid_tier_2_input_token_count/usage"
TIER3 = "generativelanguage.googleapis.com/quota/generate_content_paid_tier_3_input_token_count/usage"


def series(model, *values):
    return {"metric": {"labels": {"model": model}}, "points": [{"value": {"int64Value": str(v)}} for v in values]}


def fake_google(by_metric, descriptors=(TIER2, TIER3), pages=False):
    calls = []

    def get(path, params):
        calls.append((path, dict(params)))
        if path.endswith("/metricDescriptors"):
            internal = "generativelanguage.googleapis.com/quota/generate_content_paid_tier_1_input_tokens_internal"
            return {"metricDescriptors": [{"type": t} for t in (*descriptors, f"{internal}/usage")]}
        metric = re.search(r'metric.type="([^"]+)"', params["filter"]).group(1)
        found = by_metric.get(metric, [])
        if pages and len(found) > 1 and "pageToken" not in params:
            return {"timeSeries": found[:1], "nextPageToken": "p2"}
        return {"timeSeries": found[1:] if "pageToken" in params else found}

    get.calls = calls
    return get


def test_google_tokens_add_every_paid_tier_and_follow_pages():
    get = fake_google({TIER2: [series(FLASH, 1000, 500)], TIER3: [series(FLASH, 200), series("gemini-3.1-pro", 40)],
                       OUT: [series(FLASH, 300)]}, pages=True)
    start, end = NOW - timedelta(days=14), NOW
    assert google_usage.google_tokens("archie-email", start, end, get) == {
        FLASH: {"in": 1700, "out": 300}, "gemini-3.1-pro": {"in": 40, "out": 0}}
    queried = [p["filter"] for path, p in get.calls if path.endswith("/timeSeries")]
    assert not any("internal" in f for f in queried)
    assert all(path.startswith("projects/archie-email/") for path, _ in get.calls)


def record(home, prompt, out, when):
    Budget(home, 15, clock=lambda: when).record(FLASH, "fast", prompt, out, 0)


def test_matching_counts_show_both_figures_and_no_warning(tmp_path):
    home = init_home(tmp_path / "h")
    record(home, 1_000_000, 200_000, NOW - timedelta(hours=1))  # $0.75 + $0.75
    get = fake_google({TIER2: [series(FLASH, 1_000_000)], OUT: [series(FLASH, 200_000)]})
    entry = google_usage.check(home, "archie-email", NOW, get)
    assert entry["archie_usd"] == pytest.approx(1.5) and entry["google_usd"] == pytest.approx(1.5)
    assert google_usage.load(home, NOW) == entry
    assert google_usage.warning(entry) is None
    assert google_usage.status_line(entry) == "Google's count this month: $1.50 (Archie logged $1.50)"
    assert google_usage.subtitle(home, NOW) == " · Google: $1.50"


def test_more_than_a_dollar_apart_is_a_warning_everywhere(tmp_path):
    home = init_home(tmp_path / "h")
    record(home, 200_000, 0, NOW - timedelta(hours=1))  # $0.15
    get = fake_google({TIER2: [series(FLASH, 3_000_000)], OUT: [series(FLASH, 0)]})  # $2.25
    entry = google_usage.check(home, "archie-email", NOW, get)
    expected = "Google counts $2.10 more Gemini use this month than Archie logged ($2.25 vs $0.15)"
    assert google_usage.warning(entry) == expected
    assert google_usage.status_line(entry) == f"Warning: {expected}"
    assert google_usage.subtitle(home, NOW) == " · Google: $2.25, out of step"
    cfg = {"llm": {"google_project": "archie-email"}}
    assert doctor.check_google_usage(home, cfg, clock=lambda: NOW) == (False, expected)


def test_calls_in_the_last_few_minutes_are_left_out_on_both_sides(tmp_path):
    home = init_home(tmp_path / "h")
    record(home, 1_000_000, 0, NOW - timedelta(minutes=1))  # Google hasn't counted this yet
    get = fake_google({TIER2: [], OUT: []})
    entry = google_usage.check(home, "archie-email", NOW, get)
    assert entry["archie_usd"] == 0 and entry["google_usd"] == 0
    end = [p["interval.endTime"] for path, p in get.calls if path.endswith("/timeSeries")][0]
    assert end == (NOW - google_usage.LAG).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_google_model_names_without_preview_are_priced_as_the_preview():
    assert google_usage.priced("gemini-3.1-pro") == "gemini-3.1-pro-preview"
    assert google_usage.priced(FLASH) == FLASH
    assert google_usage.priced("gemini-9-ultra") == "gemini-9-ultra"


def test_a_failed_check_is_recorded_and_never_raises(tmp_path):
    home = init_home(tmp_path / "h")

    def broken(path, params):
        raise RuntimeError("Google access doesn't include monitoring: run `archie admin connect google` again")

    entry = google_usage.check(home, "archie-email", NOW, broken)
    assert "google_usd" not in entry
    assert google_usage.status_line(entry) == ("Google's token count: couldn't check (Google access doesn't include "
                                               "monitoring: run `archie admin connect google` again)")
    assert google_usage.subtitle(home, NOW) == ""
    ok, msg = doctor.check_google_usage(home, {"llm": {"google_project": "archie-email"}}, clock=lambda: NOW)
    assert not ok and "couldn't check" in msg


def test_last_months_check_is_not_shown(tmp_path):
    home = init_home(tmp_path / "h")
    google_usage.check(home, "archie-email", NOW, fake_google({}))
    assert google_usage.load(home, NOW + timedelta(days=20)) is None


def test_doctor_skips_the_check_without_a_project_and_waits_for_the_first_sync(tmp_path):
    home = init_home(tmp_path / "h")
    assert doctor.check_google_usage(home, {"llm": {}}) is None
    ok, msg = doctor.check_google_usage(home, {"llm": {"google_project": "archie-email"}}, clock=lambda: NOW)
    assert ok and "next sync" in msg


def test_sync_checks_google_only_when_a_project_is_set(tmp_path, monkeypatch):
    seen, said = [], []
    monkeypatch.setattr(google_usage, "check", lambda home, project, now=None, get=None: seen.append(project))
    ctx = make_ctx(tmp_path)
    asyncio.run(run_cycle(ctx, [], index=False))
    assert seen == []
    ctx.config["llm"]["google_project"] = "archie-email"
    asyncio.run(run_cycle(ctx, [], index=False, on_progress=said.append))
    assert seen == ["archie-email"] and said[-1] == "Checking Google's token count…"
