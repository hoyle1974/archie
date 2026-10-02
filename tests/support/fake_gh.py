"""Fake `gh api` runner: maps path prefixes to JSON responses and records calls."""

from __future__ import annotations


class FakeGh:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        for prefix, resp in self.routes.items():
            if path.startswith(prefix):
                return resp(path) if callable(resp) else resp
        raise KeyError(path)


def pr_item(n, title, author, repo="acme/auth", state="open", updated="2026-09-30T18:00:00Z", body=""):
    return {"number": n, "title": title, "user": {"login": author}, "state": state, "updated_at": updated,
            "created_at": "2026-09-29T10:00:00Z", "body": body, "html_url": f"https://github.com/{repo}/pull/{n}",
            "repository_url": f"https://api.github.com/repos/{repo}", "pull_request": {"url": "x"}}
