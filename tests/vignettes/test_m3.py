"""M3 vignettes (docs/VIGNETTES.md): A (standup), C (across channels), D, E, F, M."""

from datetime import datetime, timezone

from archie.derive.loops import load_loops
from tests.vignettes.week import Week


def test_A_standup_briefing(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 1, 16, 45, tzinfo=timezone.utc), work=True)  # 9:45 AM
    out = w.ask("prep me for standup")
    assert out.splitlines()[0] == "10:00 AM · Daily Standup · 15 min"
    yesterday = out.split("Yesterday", 1)[1].split("\n\n", 1)[0]
    assert "Lower token TTL to 15m" in yesterday and "ENG-398 Session cleanup job" in yesterday
    assert "Approved PR #418 Redis fallback patch" in yesterday
    assert "ENG-402 Token expiry fix (In Progress)" in out.split("Today", 1)[1]


def test_C_email_ask_closed_by_github_review(tmp_path):
    w = Week(tmp_path, work=True)
    sarah = [lp for lp in load_loops(w.ctx.home) if lp.meta["counterpart"] == "sarah_jones"]
    assert sarah and sarah[0].meta["status"] == "done"
    assert sarah[0].meta["closed_by"]["file"] == "sources/github/acme__auth/pr-418.json"


def test_D_what_next(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 1, 20, 10, tzinfo=timezone.utc), work=True)  # 1:10 PM
    out = w.ask("what should I work on next?")
    assert out.startswith("You have 50 minutes before Design Review: Auth Redesign (2:00 PM).")
    assert "fallback logic" in out.split("Do next", 1)[1].split("\n")[1]  # Alex is in the 2pm: ranks first
    assert "ENG-402 Token expiry fix (In Progress)" in out


def test_E_ledger(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 2, 22, 30, tzinfo=timezone.utc), work=True)
    out = w.ask("what did I get done this week?")
    first = out.splitlines()[0]
    assert first.startswith("Sep 28 – Oct 2:")
    assert "1 commit" in first and "1 review" in first and "1 issue closed" in first
    assert "Lower token TTL to 15m" in out


def test_F_who_touched_the_config(tmp_path):
    w = Week(tmp_path, work=True)
    w.ask("who changed config/auth.yaml last week?")
    assert "Lower token TTL to 15m" in w.llm.saw("answer")
    assert "config/auth.yaml" in w.llm.saw("answer")


def test_M_conflicting_sources_reach_the_briefing(tmp_path):
    w = Week(tmp_path, now=datetime(2026, 10, 1, 20, 45, tzinfo=timezone.utc), work=True)
    w.ask("prep me for the design review")
    seen = w.llm.saw("answer")
    assert "auth migration is paused pending security review" in seen  # Priya's email
    assert "Fix redis connection pool drop" in seen and "auth-v2 migration needs this" in seen  # Alex's PR
