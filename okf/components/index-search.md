---
type: Component
title: Index and search
description: Chunking, local embeddings (bge-small-en-v1.5, 384-d), FTS5 + sqlite-vec, hybrid search merged with RRF.
resource: archie/index/
status: planned
tags: [component]
---

The database is disposable ([principle](../principles/disposable-index.md)). The meta table holds the model and chunker version; a mismatch means a full reindex. Design: [DESIGN §5.3–5.4](../../docs/DESIGN.md#53-chunking).
