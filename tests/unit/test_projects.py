from archie.derive.projects import derive_projects
from archie.store.fence import get_fence
from archie.store.files import read_note, write_note
from tests.support.fixtures import make_ctx
from tests.unit.test_activity import seed


def paths(ctx):
    return sorted((ctx.home / "sources").rglob("*.json"))


def test_repo_and_jira_project_notes_with_timeline(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    derive_projects(ctx, paths(ctx))
    repo = read_note(ctx.home / "projects/acme-auth.md")
    assert repo.meta["aliases"] == ["acme/auth", "auth"] and repo.meta["kind"] == "repo"
    fence = get_fence(repo.body)
    assert "Lower token TTL to 15m" in fence and "PR #415 Token expiry fix (merged)" in fence
    eng = read_note(ctx.home / "projects/eng.md")
    assert eng.meta["aliases"] == ["ENG"] and "ENG-402 Token expiry fix (Done)" in get_fence(eng.body)


def test_user_edits_survive(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    derive_projects(ctx, paths(ctx))
    p = ctx.home / "projects/acme-auth.md"
    note = read_note(p)
    note.meta["aliases"].append("auth redesign")
    note.meta["description"] = "Session and token service"
    write_note(p, note)
    derive_projects(ctx, paths(ctx))
    again = read_note(p)
    assert "auth redesign" in again.meta["aliases"] and again.meta["description"] == "Session and token service"
