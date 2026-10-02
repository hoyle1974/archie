from archie.derive.github_loops import derive_github_loops
from archie.derive.loops import load_loops
from archie.store.files import write_raw
from tests.support.fixtures import make_ctx


def pr(home, state="open", requested=True, reviews=(), merged=False):
    path = home / "sources/github/acme__auth/pr-412.json"
    write_raw(path, {"repo": "acme/auth", "number": 412, "kind": "pr", "title": "Fix redis connection pool drop",
                     "author": "alexr", "state": state, "body": "", "created": "2026-09-30T10:00:00Z",
                     "updated": "2026-09-30T18:00:00Z", "url": "u", "review_requested_me": requested, "me": "ttesterson",
                     "comments": [], "merged": merged, "reviews": list(reviews)})
    return path


def test_review_request_opens_a_loop(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_github_loops(ctx, [pr(ctx.home)])
    [lp] = load_loops(ctx.home)
    assert lp.meta["kind"] == "asked_of_me" and lp.meta["summary"] == "Review PR #412: Fix redis connection pool drop"
    assert lp.meta["counterpart_name"] == "alexr"
    assert lp.meta["sources"][0] == {"file": "sources/github/acme__auth/pr-412.json", "chunk": "c0",
                                     "quote": "Fix redis connection pool drop"}


def test_my_review_closes_it_with_evidence(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_github_loops(ctx, [pr(ctx.home)])
    review = {"author": "ttesterson", "state": "APPROVED", "body": "LGTM", "date": "2026-10-01T09:00:00Z"}
    derive_github_loops(ctx, [pr(ctx.home, requested=False, reviews=[review])])
    [lp] = load_loops(ctx.home)
    assert lp.meta["status"] == "done" and lp.meta["closed_by"]["chunk"] == "c1"


def test_closed_pr_closes_it(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_github_loops(ctx, [pr(ctx.home)])
    derive_github_loops(ctx, [pr(ctx.home, state="closed", requested=False, merged=True)])
    assert load_loops(ctx.home)[0].meta["status"] == "done"


def test_rerun_does_not_duplicate(tmp_path):
    ctx = make_ctx(tmp_path)
    p = pr(ctx.home)
    derive_github_loops(ctx, [p])
    derive_github_loops(ctx, [p])
    assert len(load_loops(ctx.home)) == 1
