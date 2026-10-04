---
type: Component
title: Store
description: File I/O for ~/.archie, covering the home layout, atomic writes, frontmatter notes, raw JSON mirrors, tombstones and fences.
resource: archie/store/
status: active
tags: [component]
---

The only module that writes Archie's files. It enforces the [fence rule](../principles/fence-rule.md) and [files are the source of truth](../principles/files-source-of-truth.md).

- `home.py`: `Home` (the root comes from `ARCHIE_HOME`, falling back to `~/.archie`) and `init_home()`. `init_home()` creates the layout and `.gitignore` and never overwrites the user's files.
- `files.py`:
  - `atomic_write` writes to a temp file and then renames it.
  - `Note`/`read_note`/`write_note` handle YAML frontmatter. Timestamps stay as strings and key order is preserved.
  - `write_raw`/`read_raw` write stable JSON with sorted keys, so the same payload always produces the same bytes and the same hash.
  - `tombstone` marks a raw file as deleted.
- `lock.py`: `WriterLock` takes an advisory flock on `~/.archie/.lock` so only one process syncs or rebuilds (DESIGN §3.1). The lock is released automatically if the process dies.
- `times.py`: stored times are UTC, shown times are local ([principle](../principles/utc-stored-local-shown.md)). `utc_iso` normalizes a stored time (plain dates pass through), `when` formats one for reading ("Fri Oct 2, 1:26 PM"), and `stamp` is an answer's first line ("Sun, Oct 4 · 9:34 AM").
- `fence.py`: `get_fence`/`set_fence` read and replace named `<!-- archie:NAME -->` fences. Damaged markers raise `FenceError` rather than risk overwriting the user's text.

Known limit: rewriting a note re-renders its frontmatter, so YAML comments in frontmatter are lost.

Design: [DESIGN §4](../../docs/DESIGN.md#4-storage-layout).
