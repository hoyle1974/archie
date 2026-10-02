from datetime import datetime, timezone

from archie.activity import my_activity
from archie.store.files import write_raw
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

T0, T1 = datetime(2026, 9, 30, 0, tzinfo=timezone.utc), datetime(2026, 10, 1, 0, tzinfo=timezone.utc)


def seed(ctx):
    h = ctx.home
    write_raw(h / "sources/github/acme__auth/commit-9f3c1e2.json", {
        "sha": "9f3c1e2aa", "repo": "acme/auth", "message": "Lower token TTL to 15m\n\nbody", "date": "2026-09-30T20:00:00Z",
        "author": "ttesterson", "url": "u", "files": ["config/auth.yaml"]})
    write_raw(h / "sources/github/acme__auth/pr-415.json", {
        "repo": "acme/auth", "number": 415, "kind": "pr", "title": "Token expiry fix", "author": "ttesterson",
        "state": "closed", "body": "", "created": "2026-09-29T10:00:00Z", "updated": "2026-09-30T13:00:00Z", "url": "u",
        "review_requested_me": False, "me": "ttesterson", "comments": [], "merged": True,
        "merged_at": "2026-09-30T13:00:00Z", "reviews": []})
    write_raw(h / "sources/github/acme__auth/pr-412.json", {
        "repo": "acme/auth", "number": 412, "kind": "pr", "title": "Fix redis pool", "author": "alexr", "state": "open",
        "body": "", "created": "2026-09-29T10:00:00Z", "updated": "2026-09-30T18:00:00Z", "url": "u",
        "review_requested_me": False, "me": "ttesterson", "comments": [], "merged": False,
        "reviews": [{"author": "ttesterson", "state": "APPROVED", "body": "LGTM", "date": "2026-09-30T18:00:00Z"}]})
    write_raw(h / "sources/jira/ENG-402.json", {
        "key": "ENG-402", "summary": "Token expiry fix", "type": "Bug", "status": "Done", "status_category": "done",
        "assignee": {"id": "acc-test", "name": "Test", "email": ""}, "reporter": {"id": "p", "name": "Priya", "email": ""},
        "assignee_me": True, "priority": "", "due": None, "created": "2026-09-20T00:00:00+00:00",
        "updated": "2026-09-30T21:00:00+00:00", "description": "", "comments": [], "url": "u",
        "transitions": [{"date": "2026-09-30T21:00:00+00:00", "from": "In Progress", "to": "Done", "by_me": True}]})
    write_raw(h / "sources/drive/d1.json", {"id": "d1", "title": "Auth notes", "modified": "2026-09-30T15:00:00Z",
                                           "modified_by": "test@acme.example", "owners": [], "text": "x"})
    write_thread(h, "t1", [msg("m1", "test@acme.example", "Test", [addr("ken@acme.example", "Ken Ito")],
                               "2026-09-30T17:00:00+00:00", "Numbers attached.", subject="Q4 numbers", from_me=True)])
    write_raw(h / "sources/github/acme__auth/commit-old.json", {
        "sha": "0ld", "repo": "acme/auth", "message": "Old", "date": "2026-09-01T00:00:00Z", "author": "ttesterson",
        "url": "u", "files": []})


def test_activity_in_window_is_code_computed_and_cited(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    items = my_activity(ctx, T0, T1)
    kinds = sorted(i.kind for i in items)
    assert kinds == ["commit", "doc_edited", "email_sent", "issue_done", "pr_merged", "review_given"]
    commit = next(i for i in items if i.kind == "commit")
    assert commit.title == "Lower token TTL to 15m" and commit.project == "acme/auth"
    assert commit.path == "sources/github/acme__auth/commit-9f3c1e2.json" and commit.chunk == "c0"
    review = next(i for i in items if i.kind == "review_given")
    assert review.title == "Approved PR #412 Fix redis pool" and review.chunk == "c1"
    assert next(i for i in items if i.kind == "email_sent").title == "Q4 numbers (to Ken Ito)"
    assert [i.when for i in items] == sorted(i.when for i in items)
