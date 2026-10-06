"""An httpx.Client stand-in for web page fetches (connectors/web.py): tests never touch the network."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace


def page(body: str | bytes, kind: str = "text/html; charset=utf-8", status: int = 200, final: str | None = None,
         error: Exception | None = None) -> dict:
    """`final`: the address a client that follows redirects itself would report."""
    return {"body": body.encode() if isinstance(body, str) else body, "kind": kind, "status": status,
            "final": final, "error": error, "location": None}


def redirect(to: str, status: int = 302) -> dict:
    return {**page(""), "status": status, "location": to}


def html(title: str, text: str) -> str:
    return (f"<html><head><title>{title}</title><script>var x = 1;</script></head>"
            f"<body><nav>Home | About</nav><h1>{title}</h1><p>{text}</p></body></html>")


class FakeWeb:
    def __init__(self, pages: dict[str, dict]):
        self.pages = pages
        self.requests: list[str] = []
        self.read: list[str] = []  # urls whose body was downloaded

    @contextmanager
    def stream(self, method: str, url: str):
        self.requests.append(url)
        p = self.pages.get(url) or page("not found", status=404)
        if p["error"]:
            raise p["error"]

        def iter_bytes():
            self.read.append(url)
            body = p["body"]
            for i in range(0, len(body), 65536):
                yield body[i:i + 65536]

        headers = {"content-type": p["kind"], **({"location": p["location"]} if p["location"] else {})}
        yield SimpleNamespace(url=p["final"] or url, status_code=p["status"], headers=headers, iter_bytes=iter_bytes)
