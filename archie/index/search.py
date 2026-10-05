"""Hybrid search: FTS5 for exact tokens, vectors for meaning, merged with RRF (DESIGN §5.4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import sqlite_vec

from archie.derive.ignore import on_list
from archie.index.chunk import signature_key
from archie.index.db import Index

POOL = 50  # candidates taken from each side before filtering and fusing (at least 2×k)


@dataclass
class Hit:
    path: str
    chunk_id: str
    text: str
    source: str
    ts: str | None
    char_start: int
    char_end: int
    people: list[str] = field(default_factory=list)
    label: str = ""
    sender: str = ""
    score: float = 0.0


def rrf_scores(rankings: list[list], k: int = 60, weights: list[float] | None = None) -> dict:
    """Reciprocal Rank Fusion: each item scores the sum of weight/(k + rank) across rankings."""
    scores: dict = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights else 1.0
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + w / (k + rank + 1)
    return scores


def rrf(rankings: list[list], k: int = 60) -> list:
    """Items of every ranking, best fused score first."""
    scores = rrf_scores(rankings, k)
    return sorted(scores, key=lambda x: -scores[x])


def _fts_query(q: str) -> str:
    tokens = re.findall(r"[\w][\w\-./@]*", q)
    return " OR ".join('"' + t.replace('"', "") + '"' for t in tokens)


def _fts_ids(idx: Index, q: str, pool: int = POOL) -> list[int]:
    fq = _fts_query(q)
    if not fq:
        return []
    rows = idx.query("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (fq, pool))
    return [r[0] for r in rows]


def _vec_ids(idx: Index, q: str, pool: int = POOL) -> list[int]:
    v = idx.embedder.embed([q], query=True)[0]
    rows = idx.query(
        "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(v), pool))
    # vec0 default metric is L2; for unit vectors cosine = 1 - d²/2.
    return [r[0] for r in rows if 1 - (r[1] ** 2) / 2 >= idx.embedder.min_similarity]


def search(idx: Index, query: str, k: int = 10, source: str | None = None, since: str | None = None,
           until: str | None = None, people: list[str] | None = None, skip_senders: list[str] | None = None,
           senders: list[str] | None = None) -> list[Hit]:
    pool = max(POOL, 2 * k)
    scores = rrf_scores([_fts_ids(idx, query, pool), _vec_ids(idx, query, pool)])
    hits, signatures = [], set()
    for rowid in sorted(scores, key=lambda x: -scores[x]):
        rows = idx.query(
            "SELECT path, chunk_id, text, source, ts, char_start, char_end, people, label, sender"
            " FROM chunks WHERE id = ?", (rowid,))
        if not rows:
            continue
        row = rows[0]
        hit = Hit(*row[:7], people=json.loads(row[7] or "[]"), label=row[8], sender=row[9] or "",
                  score=scores[rowid])
        if source and hit.source != source:
            continue
        if since and (hit.ts or "") < since:
            continue
        if until and (hit.ts or "9999") > until:
            continue
        if people and not set(people) & (set(hit.people) | {hit.sender}):
            continue
        if skip_senders and on_list(hit.sender, skip_senders):
            continue
        if senders and not on_list(hit.sender, senders):
            continue
        sig = signature_key(hit.source, hit.chunk_id, hit.sender, hit.text)
        if sig in signatures:
            continue
        if sig:
            signatures.add(sig)
        hits.append(hit)
        if len(hits) == k:
            break
    return hits
