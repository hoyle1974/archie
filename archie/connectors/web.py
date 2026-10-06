"""Web pages for the dig loop's `web` step (spec: dig-deeper §3). Read-only.

The backend's `web_links` finds a few links for a query (Gemini with Google Search
grounding; its text is thrown away). Each page is fetched over HTTPS from a public address
(every redirect hop checked) with a time limit, a size limit and only text types, reduced to
plain text, and saved as
sources/web/<sha1 of url>.json before anything cites it, so a web fact is checked against a
file like any other. A page fetched in the last 7 days is reused from its file. Saved pages
are indexed at once (the dig needs their chunks now) and kept like every source.

Queries are names, organisations and topics: one with an address, a link, a long number or
more than 8 words is refused, so nothing from the user's mail is sent out."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from archie.connectors.pagetext import html_title, page_text
from archie.index.chunk import chunk_windows, register_raw_chunker, short_date
from archie.store.files import read_raw, write_raw

if TYPE_CHECKING:
    from archie.ask.context import Ctx

NAME = "web"
LINKS = 3
TIMEOUT_S = 10
MAX_BYTES = 2_000_000
MIN_TEXT = 200  # shorter pages (logins, consent walls, redirects) say nothing
REUSE = timedelta(days=7)
CHUNKS_PER_PAGE = 4
TYPES = ("text/html", "text/plain")
AGENT = "Archie/1 (a personal archive assistant; read-only)"
MAX_HOPS = 5
REDIRECTS = (301, 302, 303, 307, 308)
_LOCAL = re.compile(r"(^localhost$|\.(local|localhost|internal|lan|home|arpa)$)", re.I)


def query_problem(query: str) -> str | None:
    if "@" in query:
        return "a web query can't contain an email address"
    if "://" in query:
        return "a web query can't contain a link"
    if re.search(r"\d{5,}", query):
        return "a web query can't contain long numbers"
    if len(query.split()) > 8:
        return "a web query is at most 8 words"
    return None


def page_path(url: str) -> str:
    return f"sources/{NAME}/{hashlib.sha1(url.encode()).hexdigest()}.json"


def _client(ctx: Ctx):
    if ctx.web is not None:
        return ctx.web
    import httpx

    return httpx.Client(follow_redirects=False, timeout=TIMEOUT_S, headers={"User-Agent": AGENT})


def public(url: str, resolve: bool = True) -> bool:
    """An https address on the public internet. Every redirect hop is checked, so a page can't
    send the fetcher to the local network or over plain http. `resolve` also looks the name up
    and refuses private, loopback and link-local addresses (off for a test client)."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or _LOCAL.search(host):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if not resolve:
        return True
    try:
        found = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(found) and all(ipaddress.ip_address(f[4][0].split("%")[0]).is_global for f in found)


def _fresh(ctx: Ctx, rel: str) -> bool:
    p = ctx.home / rel
    if not p.exists():
        return False
    try:
        fetched = datetime.fromisoformat(read_raw(p).get("fetched_at") or "")
    except ValueError:
        return False
    return ctx.now - fetched < REUSE


def fetch(ctx: Ctx, url: str, query: str, title: str = "", client=None) -> str | None:
    """The saved page's path (relative to the home), or None when it couldn't be read."""
    real = ctx.web is None  # a real connection: look names up before connecting
    client = client or _client(ctx)
    deadline = time.monotonic() + TIMEOUT_S  # for the whole fetch, not each read
    try:
        for _ in range(MAX_HOPS + 1):
            if not public(url, resolve=real):
                return None
            with client.stream("GET", url) as r:
                if r.status_code in REDIRECTS and r.headers.get("location"):
                    url = urljoin(str(r.url), r.headers["location"])
                    continue
                final = str(r.url)
                if not public(final, resolve=False) or r.status_code != 200:
                    return None
                rel = page_path(final)
                if _fresh(ctx, rel):
                    return rel
                kind = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                if kind not in TYPES:
                    return None
                body = bytearray()
                for piece in r.iter_bytes():
                    body += piece
                    if len(body) > MAX_BYTES or time.monotonic() > deadline:
                        return None
                charset = re.search(r"charset=([\w-]+)", r.headers.get("content-type") or "")
                raw = bytes(body).decode(charset.group(1) if charset else "utf-8", errors="replace")
                break
        else:
            return None  # too many redirects
    except Exception:  # timeouts, TLS and network errors: the page just isn't read
        return None
    text = page_text(raw) if kind == "text/html" else raw.strip()
    if len(text) < MIN_TEXT:
        return None
    write_raw(ctx.home / rel, {"url": final, "title": (html_title(raw) if kind == "text/html" else "") or title,
                               "fetched_at": ctx.now.isoformat(), "query": query, "text": text})
    return rel


def _best(chunks: list[dict], query: str) -> list[dict]:
    words = {w.lower() for w in re.findall(r"\w{3,}", query)}
    return sorted(chunks, key=lambda c: -sum(c["text"].lower().count(w) for w in words))[:CHUNKS_PER_PAGE]


def web_search(ctx: Ctx, query: str) -> list[dict]:
    """Chunks of up to LINKS saved pages for the query, the parts that mention it most first."""
    from archie.llm.backend import LLMError

    try:
        links = ctx.backend.web_links(query, LINKS)
    except LLMError:
        return []
    client, rels = None, []
    for link in links:
        client = client or _client(ctx)
        rel = fetch(ctx, link.get("url") or "", query, link.get("title") or "", client)
        if rel and rel not in rels:
            rels.append(rel)
    if not rels:
        return []
    ctx.index.update_files(rels)
    return [c for rel in rels for c in _best(ctx.index.chunks_of(rel), query)]


def chunk_page(path: str, data: dict) -> list:
    title = data.get("title") or urlparse(data.get("url") or "").netloc or "a web page"
    label = f"Web: {title} (fetched {short_date(data.get('fetched_at'))})"
    head = f"Web page: {title}\n{data.get('url', '')}\n\n"
    chunks = chunk_windows(path, head + (data.get("text") or ""), source=NAME, ts=data.get("fetched_at"))
    for c in chunks:
        c.label = label
    return chunks


register_raw_chunker(NAME, chunk_page)
