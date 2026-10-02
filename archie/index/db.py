"""The disposable SQLite index (DESIGN §5.4): FTS5 + sqlite-vec over chunks of files.

Nothing here is a source of truth. Delete archie.db and `sync()` rebuilds it from files.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from archie.index.chunk import CHUNKER_VERSION, Chunk, chunk_file
from archie.index.embed import Embedder
from archie.store.home import Home

SCHEMA_VERSION = "2"
# Only these top-level parts of the home are indexed; config, state and logs are not.
INDEXED_ROOTS = ("sources", "people", "projects", "meetings", "briefings", "loops", "journal")


@dataclass
class SyncStats:
    indexed: int = 0
    removed: int = 0
    chunks: int = 0


class Index:
    def __init__(self, home: Home, embedder: Embedder, path: Path | None = None):
        self.home = home
        self.embedder = embedder
        self.conn = sqlite3.connect(path or home.db, check_same_thread=False)  # TUI runs sync in a worker thread
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    # -- schema -----------------------------------------------------------------------
    def _wanted_meta(self) -> dict[str, str]:
        return {"schema_version": SCHEMA_VERSION, "chunker_version": CHUNKER_VERSION,
                "embed_model": self.embedder.name, "dim": str(self.embedder.dim)}

    def _ensure_schema(self) -> None:
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        have = dict(c.execute("SELECT key, value FROM meta"))
        if have != self._wanted_meta():
            for t in ("files", "chunks", "chunks_fts", "chunks_vec"):
                c.execute(f"DROP TABLE IF EXISTS {t}")
            c.execute("DELETE FROM meta")
            c.executemany("INSERT INTO meta VALUES (?, ?)", self._wanted_meta().items())
        c.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, sha256 TEXT, indexed_at TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, chunk_id TEXT, path TEXT, char_start INT, char_end INT,
            source TEXT, ts TEXT, people TEXT, label TEXT, text TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='unicode61')")
        c.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[{self.embedder.dim}])")
        c.commit()

    # -- sync -------------------------------------------------------------------------
    def _files_on_disk(self) -> dict[str, Path]:
        found = {}
        for root in INDEXED_ROOTS:
            base = self.home.root / root
            if not base.is_dir():
                continue
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".json") and not p.name.startswith("."):
                    found[p.relative_to(self.home.root).as_posix()] = p
        return found

    def _drop(self, path: str) -> None:
        ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE path = ?", (path,))]
        for i in ids:
            self.conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (i,))
            self.conn.execute("DELETE FROM chunks_vec WHERE rowid = ?", (i,))
        self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,))

    def _insert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vecs = self.embedder.embed([c.text for c in chunks])
        for c, v in zip(chunks, vecs):
            cur = self.conn.execute(
                "INSERT INTO chunks(chunk_id, path, char_start, char_end, source, ts, people, label, text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (c.chunk_id, c.path, c.char_start, c.char_end, c.source, c.ts, json.dumps(c.people),
                 c.label or c.path, c.text))
            self.conn.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (cur.lastrowid, c.text))
            self.conn.execute("INSERT INTO chunks_vec(rowid, embedding) VALUES (?, ?)",
                              (cur.lastrowid, sqlite_vec.serialize_float32(v)))

    def sync(self) -> SyncStats:
        stats = SyncStats()
        known = dict(self.conn.execute("SELECT path, sha256 FROM files"))
        disk = self._files_on_disk()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for rel in sorted(set(known) - set(disk)):
            self._drop(rel)
            self.conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            stats.removed += 1
        for rel, p in sorted(disk.items()):
            text = p.read_text(encoding="utf-8")
            digest = hashlib.sha256(text.encode()).hexdigest()
            if known.get(rel) == digest:
                continue
            self._drop(rel)
            chunks = chunk_file(rel, text)
            self._insert(chunks)
            self.conn.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?)", (rel, digest, now))
            stats.indexed += 1
            stats.chunks += len(chunks)
            self.conn.commit()
        self.conn.commit()
        return stats

    def chunk_text(self, path: str, chunk_id: str) -> str | None:
        row = self.conn.execute("SELECT text FROM chunks WHERE path = ? AND chunk_id = ?", (path, chunk_id)).fetchone()
        return row[0] if row else None

    def chunks_with_people(self, emails: list[str], limit: int = 200) -> list[dict]:
        """Chunks whose people include any of these emails, newest first (code-computed history)."""
        if not emails:
            return []
        where = " OR ".join("people LIKE ?" for _ in emails)
        rows = self.conn.execute(
            f"SELECT path, chunk_id, text, source, ts, label FROM chunks WHERE {where} ORDER BY ts DESC LIMIT ?",
            [f'%"{e.lower()}"%' for e in emails] + [limit])
        return [dict(zip(("path", "chunk_id", "text", "source", "ts", "label"), r)) for r in rows]

    def chunks_of(self, path: str) -> list[dict]:
        rows = self.conn.execute("SELECT path, chunk_id, text, source, ts, label FROM chunks WHERE path = ? ORDER BY id",
                                 (path,))
        return [dict(zip(("path", "chunk_id", "text", "source", "ts", "label"), r)) for r in rows]

    def counts(self) -> dict[str, int]:
        return {"files": self.conn.execute("SELECT count(*) FROM files").fetchone()[0],
                "chunks": self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]}
