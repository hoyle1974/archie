import asyncio
from datetime import datetime, timezone

from archie.connectors.base import SyncCtx
from archie.connectors.github import GitHubConnector
from archie.config import Me
from archie.index.chunk import chunk_file
from archie.store.files import read_raw
from archie.store.home import init_home
from tests.support.fake_gh import FakeGh, pr_item

NOW = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
ME = Me(name="Test", emails=["test@acme.example"], github="ttesterson")
PR = pr_item(412, "Fix redis connection pool drop", "alexr", body="Pool was dropping under load.")
MINE = pr_item(415, "Token expiry fix", "ttesterson", state="closed", body="Fixes ENG-402.")


def routes():
    return {
        "search/issues?q=involves:ttesterson": {"items": [PR, MINE]},
        "search/issues?q=is:pr+is:open+review-requested:ttesterson": {"items": [PR]},
        "search/commits?q=author:ttesterson": {"items": [{"sha": "9f3c1e2", "repository": {"full_name": "acme/auth"}}]},
        "repos/acme/auth/pulls/412/reviews": [],
        "repos/acme/auth/pulls/415/reviews": [{"user": {"login": "alexr"}, "state": "APPROVED", "body": "LGTM",
                                              "submitted_at": "2026-09-30T12:00:00Z"}],
        "repos/acme/auth/pulls/412": {"merged": False, "merged_at": None, "state": "open", "head": {"ref": "fix-pool"}},
        "repos/acme/auth/pulls/415": {"merged": True, "merged_at": "2026-09-30T13:00:00Z", "state": "closed",
                                      "head": {"ref": "expiry"}},
        "repos/acme/auth/issues/412/comments": [{"user": {"login": "priya"}, "body": "Is this safe to ship?",
                                                 "created_at": "2026-09-30T19:00:00Z"}],
        "repos/acme/auth/issues/415/comments": [],
        "repos/acme/auth/commits/9f3c1e2": {"sha": "9f3c1e2", "html_url": "u", "commit": {
            "message": "Lower token TTL to 15m", "author": {"name": "Test", "date": "2026-09-29T20:00:00Z"}},
            "author": {"login": "ttesterson"}, "files": [{"filename": "config/auth.yaml"}]},
    }


def run(gh, cursor=None, tmp_path=None):
    home = init_home(tmp_path / "h")
    res = asyncio.run(GitHubConnector(runner=gh).sync(SyncCtx(home, {}, ME, NOW, 14), cursor))
    return home, res


def test_sync_mirrors_prs_and_my_commits(tmp_path):
    gh = FakeGh(routes())
    home, res = run(gh, tmp_path=tmp_path)
    assert "updated:>=2026-09-17" in gh.calls[0]
    pr = read_raw(home / "sources/github/acme__auth/pr-412.json")
    assert pr["title"] == "Fix redis connection pool drop" and pr["author"] == "alexr"
    assert pr["review_requested_me"] is True and pr["comments"][0]["body"] == "Is this safe to ship?"
    mine = read_raw(home / "sources/github/acme__auth/pr-415.json")
    assert mine["merged"] is True and mine["reviews"][0]["state"] == "APPROVED"
    c = read_raw(home / "sources/github/acme__auth/commit-9f3c1e2.json")
    assert c["message"] == "Lower token TTL to 15m" and c["files"] == ["config/auth.yaml"]
    assert res.cursor == {"last_sync": NOW.isoformat()}


def test_incremental_queries_since_last_sync(tmp_path):
    gh = FakeGh(routes())
    run(gh, cursor={"last_sync": "2026-10-01T12:00:00+00:00"}, tmp_path=tmp_path)
    assert "updated:>=2026-10-01T11:00:00Z" in gh.calls[0]


def test_no_github_user_means_nothing_to_do(tmp_path):
    home = init_home(tmp_path / "h")
    res = asyncio.run(GitHubConnector(runner=FakeGh({})).sync(SyncCtx(home, {}, Me(), NOW, 14), None))
    assert res.written == []


def test_chunks_cover_pr_comments_and_commit_files(tmp_path):
    home, _ = run(FakeGh(routes()), tmp_path=tmp_path)
    pr = chunk_file("sources/github/acme__auth/pr-412.json", (home / "sources/github/acme__auth/pr-412.json").read_text())
    assert pr[0].label == "PR #412 Fix redis connection pool drop (acme/auth, by alexr)"
    assert any("Is this safe to ship?" in c.text for c in pr)
    assert "gh:alexr" in pr[0].people
    [c] = chunk_file("sources/github/acme__auth/commit-9f3c1e2.json",
                     (home / "sources/github/acme__auth/commit-9f3c1e2.json").read_text())
    assert "config/auth.yaml" in c.text and c.label.startswith("Commit 9f3c1e2: Lower token TTL")


def test_search_pages_until_short_page(tmp_path):
    many = [pr_item(i, f"PR {i}", "ttesterson") for i in range(100)]
    pages = {1: many, 2: [pr_item(100, "last", "ttesterson")]}
    r = routes()
    r["search/issues?q=involves:ttesterson"] = lambda path: {"items": pages.get(int(path.rsplit("page=", 1)[1]), [])}
    r["repos/acme/auth/pulls/"] = lambda path: [] if path.endswith("/reviews") else {"merged": False, "state": "open"}
    r["repos/acme/auth/issues/"] = []
    gh = FakeGh(r)
    home, res = run(gh, tmp_path=tmp_path)
    assert sum(1 for c in gh.calls if c.startswith("search/issues?q=involves")) == 2
    assert (home / "sources/github/acme__auth/pr-100.json").exists()
