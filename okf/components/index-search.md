---
type: Component
title: Index and search
description: Chunks files, embeds them locally with bge-small-en-v1.5 (384-d), stores them in FTS5 + sqlite-vec, and runs hybrid search merged with RRF.
resource: archie/index/
status: active
tags: [component]
---

- `chunk.py`: `chunk_file(rel_path, text)`.
  - Markdown: the frontmatter is one chunk, then one chunk per heading section. Long sections become 280-word windows overlapping by 40 words. Offsets index into the file text.
  - Raw JSON under `sources/<source>/`: goes to the chunker that connector registered with `register_raw_chunker`. Tombstoned files produce no chunks.
- `embed.py`:
  - `SentenceTransformerEmbedder` adds bge's query prefix and normalizes vectors. A vector hit counts only if its cosine similarity is at least 0.5; real bge scores showed related text at 0.50–0.61 and unrelated text around 0.42.
  - `HashEmbedder` is a deterministic embedder for tests.
  - `make_embedder(config)` picks one from the config.
- `db.py`: `Index(home, embedder)`.
  - Tables: `files` (the sha256 list), `chunks`, `chunks_fts`, `chunks_vec`, and `meta`.
  - Any mismatch in the meta table (schema, chunker version, model or dimension) wipes and rebuilds the index.
  - `sync()` re-indexes changed files and drops deleted ones.
  - Worker threads share one SQLite connection, so every read goes through `query()` under an `RLock`, and `sync()` holds the same lock.
  - Only `sources/` and the folders of derived notes are indexed; config, state and logs never are.
- `search.py`: `search(idx, q, k, source, since, until, people)`.
  - Takes the top 50 FTS hits (each token quoted and OR'ed) and the top 50 vector hits, then merges them with RRF (k=60) before filtering.

The database is disposable ([principle](../principles/disposable-index.md)), and a test proves a rebuild returns the same results. Design: [DESIGN §5.3–5.4](../../docs/DESIGN.md#53-chunking).
