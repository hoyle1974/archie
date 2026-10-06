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
  - `Chunk.sender`: the sender's address on email excerpts (set by the Gmail chunker), empty otherwise.
- `embed.py`:
  - `SentenceTransformerEmbedder` adds bge's query prefix and normalizes vectors. A vector hit counts only if its cosine similarity is at least 0.5; real bge scores showed related text at 0.50–0.61 and unrelated text around 0.42.
  - The model runs on the CPU (`index.embed_device`, default `cpu`; `mps` uses the Apple GPU). For bge-small the CPU is about twice as fast as MPS here.
  - A downloaded model loads from the local cache (`local_files_only`); only a model not yet downloaded goes to the Hugging Face Hub. Asking the Hub on every start needed the network and printed an "unauthenticated requests" warning.
  - PyTorch can't be called from two threads at once, so every model load and `encode()` in the process takes one lock (`_MODEL_LOCK`). A sync embeds one file per call, so a question's embed waits at most one file's batch.
  - `HashEmbedder` is a deterministic embedder for tests.
  - `make_embedder(config)` picks one from the config.
- `db.py`: `Index(home, embedder)`.
  - Tables: `files` (the sha256 list), `chunks`, `chunks_fts`, `chunks_vec`, and `meta`.
  - Any mismatch in the meta table (schema, chunker version, model or dimension) wipes and rebuilds the index. `CHUNKER_VERSION` 3 (email signatures as their own chunks) and 4 (a quoted "Original Message" kept out of the signature) each rebuild it once.
  - `rebuilding()` is true when the index has no chunks but there are files to index (just wiped by a version change; `ask` says so instead of "nothing found"). `update_files(paths)` re-indexes just those files now (a telling changed a person file).
  - `sync()` re-indexes changed files and drops deleted ones. It embeds each file outside the lock and writes that file's rows in one short locked transaction, so questions never wait behind a long sync.
  - Worker threads share one SQLite connection, so every read goes through `query()` under an `RLock`, and `sync()` holds the same lock.
  - Only `sources/` and the folders of derived notes are indexed; config, state and logs never are.
  - `chunks_with_people(emails, limit, before)` returns a person's chunks newest first, each with its `sender`, for the evidence selector ([ask](ask.md) `evidence.py`).
- `search.py`: `search(idx, q, k, source, since, until, people, skip_senders, senders)`.
  - Takes the top 50 FTS hits (each token quoted and OR'ed) and the top 50 vector hits, then merges them with RRF (k=60) before filtering.
  - `skip_senders` drops hits from those senders (addresses or `@domain`s); `senders`, when not empty, keeps only hits from them. Each `Hit` carries its `sender`. The same email signature (same sender and text, `signature_key`) is returned once, so a frequent signer's signatures don't crowd out their messages.
  - Schema version 3 added the `sender` column, so an older index rebuilds itself.

The database is disposable ([principle](../principles/disposable-index.md)), and a test proves a rebuild returns the same results. Design: [DESIGN §5.3–5.4](../../docs/DESIGN.md#53-chunking).
