---
type: Index
title: Components
description: The parts of Archie and where their code lives. status planned means the code does not exist yet.
---

Data flows top to bottom:

- [sync](sync.md): one cycle of connectors, then derivers, then the index
- [connectors](connectors.md): remote sources to `sources/`
- [derivers](derivers.md): `sources/` to people, meetings, loops and projects
- [index-search](index-search.md): chunking, embeddings, FTS5 and vectors, hybrid search
- [llm](llm.md): one backend interface plus the citation verifier
- [activity](activity.md): what the user did in a window, computed by code
- [enrich](enrich.md): cited facts about people, added after indexing
- [loops](loops.md): open-loop detection, closure and ranking
- [briefings](briefings.md): meeting type, templates and timing
- [ask](ask.md): router, intents and rendering, the one user entry point
- [tui](tui.md): Textual app hosting the sync loop
- [store](store.md): file I/O, frontmatter, fences, atomic writes
- [config](config.md): config.yaml, me.yaml, cursors
- [secrets](secrets.md): Keychain access that never hangs silently
- [doctor](doctor.md): setup checks with fixes
- [cli](cli.md): the `archie` command
