---
type: Log
title: Archie change log
description: Chronological history of design decisions and structural changes, newest first.
---

## 2026-10-01
- Started v1 from scratch (v0 shelved at `~/code/archie-v0`).
- Decided: files are the source of truth, SQLite is only an index, the fence rule, the LLM extracts and code checks every quote, `archie ask` is the one entry point, the TUI hosts sync with a catch-up on launch, first sync goes back 14 days and nothing is pruned, Slack waits for phase 2.
- `me.yaml` gains `legal_name` and name `aliases` (whole-word match) so mentions by name resolve to the user.
- Added the OKF bundle (describes Archie itself) and graphify (gitignored), both refreshed before every commit.
