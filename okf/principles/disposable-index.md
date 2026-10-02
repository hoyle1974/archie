---
type: Principle
title: SQLite is a disposable index
description: archie.db holds only FTS5/vector indexes and indexer bookkeeping; it can be rebuilt from files.
tags: [principle]
---

No fact may exist only in SQLite. `archie admin reindex` rebuilds it. See [index](../components/index-search.md).

Source: [DESIGN §2](../../docs/DESIGN.md#2-principles-non-negotiable)
