from archie.derive.jira_loops import derive_jira_loops
from archie.derive.loops import load_loops
from archie.llm.backend import FakeBackend
from archie.store.files import write_raw
from tests.support.fixtures import by_schema, make_ctx


def issue(home, comments, transitions=()):
    p = home / "sources/jira/ENG-402.json"
    write_raw(p, {"key": "ENG-402", "summary": "Token expiry fix", "type": "Bug", "status": "In Progress",
                  "status_category": "indeterminate", "assignee": {"id": "acc-test", "name": "Test", "email": ""},
                  "reporter": {"id": "acc-priya", "name": "Priya Sharma", "email": "priya@acme.example"},
                  "assignee_me": True, "priority": "", "due": None, "created": "2026-09-20T00:00:00+00:00",
                  "updated": "2026-09-30T00:00:00+00:00", "description": "Tokens expire early.",
                  "comments": comments, "transitions": list(transitions), "url": "u"})
    return p


ASK = {"author": {"id": "acc-priya", "name": "Priya Sharma", "email": "priya@acme.example"},
       "date": "2026-09-30T18:00:00+00:00", "body": "@Test can you finish this by Friday?", "mentions_me": True,
       "from_me": False}
MINE = {"author": {"id": "acc-test", "name": "Test", "email": ""}, "date": "2026-10-01T18:00:00+00:00",
        "body": "Done, shipped in PR 415.", "mentions_me": False, "from_me": True}


def test_mention_with_request_becomes_loop(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(loops_extract={"loops": [
        {"kind": "asked_of_me", "ref": 2, "quote": "can you finish this by Friday", "summary": "Finish ENG-402",
         "due": None, "resolved": False, "resolved_ref": None, "resolved_quote": None}]})))
    derive_jira_loops(ctx, [issue(ctx.home, [ASK])])
    [lp] = load_loops(ctx.home)
    assert lp.meta["counterpart_name"] == "Priya Sharma" and lp.meta["sources"][0]["chunk"] == "c1"


def test_comments_without_mentions_never_reach_the_model(tmp_path):
    ctx = make_ctx(tmp_path)  # no replies: a call would raise
    plain = dict(ASK, mentions_me=False)
    derive_jira_loops(ctx, [issue(ctx.home, [plain])])
    assert load_loops(ctx.home) == []


def test_my_later_comment_can_close_it(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(
        loops_extract={"loops": [{"kind": "asked_of_me", "ref": 2, "quote": "can you finish this by Friday",
                                  "summary": "Finish ENG-402", "due": None, "resolved": False, "resolved_ref": None,
                                  "resolved_quote": None}]},
        loops_close={"updates": [{"loop": 1, "resolved": True, "ref": 3, "quote": "Done, shipped in PR 415"}]})))
    derive_jira_loops(ctx, [issue(ctx.home, [ASK])])
    derive_jira_loops(ctx, [issue(ctx.home, [ASK, MINE])])
    assert load_loops(ctx.home)[0].meta["status"] == "done"
