import asyncio
from datetime import datetime, timezone

from archie.config import Me
from archie.connectors.base import SyncCtx
from archie.connectors.jira import JiraConnector, adf_text
from archie.index.chunk import chunk_file
from archie.store.files import read_raw
from archie.store.home import init_home

NOW = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
ME = Me(name="Test", jira_account_id="acc-test")


def adf(*paras):
    return {"type": "doc", "content": [{"type": "paragraph", "content": p} for p in paras]}


ISSUE = {"key": "ENG-402", "fields": {
    "summary": "Token expiry fix", "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    "assignee": {"accountId": "acc-test", "displayName": "Test Testerson", "emailAddress": "test@acme.example"},
    "reporter": {"accountId": "acc-priya", "displayName": "Priya Sharma"}, "priority": {"name": "High"},
    "duedate": "2026-10-03", "created": "2026-09-20T10:00:00.000+0000", "updated": "2026-09-30T18:00:00.000+0000",
    "description": adf([{"type": "text", "text": "Tokens expire too early."}]),
    "comment": {"comments": [{"author": {"accountId": "acc-priya", "displayName": "Priya Sharma"},
                              "created": "2026-09-30T18:00:00.000+0000",
                              "body": adf([{"type": "mention", "attrs": {"id": "acc-test", "text": "@Test"}},
                                           {"type": "text", "text": " can you finish this by Friday?"}])}]}},
    "changelog": {"histories": [{"created": "2026-09-28T09:00:00.000+0000",
                                 "author": {"accountId": "acc-test", "displayName": "Test Testerson"},
                                 "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}]}]}}


class FakeJira:
    def __init__(self, issues):
        self.issues, self.jql = issues, []

    def __call__(self, path, params):
        self.jql.append(params["jql"])
        return {"issues": self.issues, "total": len(self.issues), "startAt": 0, "maxResults": 100}


def run(fake, cursor=None, tmp_path=None):
    home = init_home(tmp_path / "h")
    res = asyncio.run(JiraConnector(client=fake).sync(SyncCtx(home, {"site": "https://acme.atlassian.net"}, ME, NOW, 14), cursor))
    return home, res


def test_adf_flattens_text_and_mentions():
    assert adf_text(ISSUE["fields"]["comment"]["comments"][0]["body"]).strip() == "@Test can you finish this by Friday?"


def test_sync_mirrors_issues_involving_me(tmp_path):
    fake = FakeJira([ISSUE])
    home, res = run(fake, tmp_path=tmp_path)
    assert "updated >= \"2026-09-17" in fake.jql[0] and "currentUser()" in fake.jql[0]
    data = read_raw(home / "sources/jira/ENG-402.json")
    assert data["status"] == "In Progress" and data["status_category"] == "indeterminate"
    assert data["assignee_me"] is True and data["due"] == "2026-10-03"
    assert data["transitions"] == [{"date": "2026-09-28T09:00:00+00:00", "from": "To Do", "to": "In Progress",
                                    "by_me": True}]
    assert data["comments"][0]["mentions_me"] is True
    assert data["url"] == "https://acme.atlassian.net/browse/ENG-402"


def test_incremental_jql_uses_cursor(tmp_path):
    fake = FakeJira([])
    run(fake, cursor={"last_sync": "2026-10-01T12:00:00+00:00"}, tmp_path=tmp_path)
    assert 'updated >= "2026-10-01 04:00"' in fake.jql[0] or 'updated >= "2026-10-01 11:00"' in fake.jql[0]


def test_chunks(tmp_path):
    home, _ = run(FakeJira([ISSUE]), tmp_path=tmp_path)
    chunks = chunk_file("sources/jira/ENG-402.json", (home / "sources/jira/ENG-402.json").read_text())
    assert chunks[0].label == "Jira ENG-402: Token expiry fix (In Progress)"
    assert "Tokens expire too early." in chunks[0].text
    assert any("can you finish this by Friday?" in c.text for c in chunks)
