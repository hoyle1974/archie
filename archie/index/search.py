"""Hybrid search: FTS5 for exact tokens, vectors for meaning, merged with RRF (DESIGN §5.4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import sqlite_vec

from archie.index.db import Index

POOL = 50  # candidates taken from each side before filtering and fusing


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
    score: float = 0.0


def rrf(rankings: list[list], k: int = 60) -> list:
    """Reciprocal Rank Fusion: sum 1/(k + rank) across rankings, best first."""
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: -scores[x])


def _fts_query(q: str) -> str:
    tokens = re.findall(r"[\w][\w\-./@]*", q)
    return " OR ".join('"' + t.replace('"', "") + '"' for t in tokens)


def _fts_ids(idx: Index, q: str) -> list[int]:
    fq = _fts_query(q)
    if not fq:
        return []
    rows = idx.conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (fq, POOL))
    return [r[0] for r in rows]


def _vec_ids(idx: Index, q: str) -> list[int]:
    v = idx.embedder.embed([q], query=True)[0]
    rows = idx.conn.execute(
        "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(v), POOL))
    # vec0 default metric is L2; for unit vectors cosine = 1 - d²/2.
    return [r[0] for r in rows if 1 - (r[1] ** 2) / 2 >= idx.embedder.min_similarity]


def search(idx: Index, query: str, k: int = 10, source: str | None = None, since: str | None = None,
           until: str | None = None, people: list[str] | None = None) -> list[Hit]:
    fused = rrf([_fts_ids(idx, query), _vec_ids(idx, query)])
    hits = []
    for rowid in fused:
        row = idx.conn.execute(
            "SELECT path, chunk_id, text, source, ts, char_start, char_end, people, label FROM chunks WHERE id = ?",
            (rowid,)).fetchone()
        if row is None:
            continue
        hit = Hit(*row[:7], people=json.loads(row[7] or "[]"), label=row[8])
        if source and hit.source != source:
            continue
        if since and (hit.ts or "") < since:
            continue
        if until and (hit.ts or "9999") > until:
            continue
        if people and not set(people) & set(hit.people):
            continue
        hits.append(hit)
        if len(hits) == k:
            break
    return hits
