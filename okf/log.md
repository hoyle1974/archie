---
type: Log
title: Archie change log
description: Chronological history of design decisions and structural changes, newest first.
---

## 2026-10-02
- M1 and M2 are done. Vignettes B, H, J and L pass. A passes for standard meetings and 1:1s, and C passes for email.
- People: inbound mail counts toward a dossier only if Gmail filed it as Personal (or the account has no categories), and never from a role address. Real data had shown 48 "people", mostly businesses, which these rules cut to 16.
- An invite to a future meeting introduces a person but is not an interaction. "Last talked" and history only count things that have already happened.
- Connectors can declare `after = (...)`. Drive runs after Calendar because it reads calendar attachments.
- Vignette tests use `tests/vignettes/week.py`, a synthetic week synced through the real connectors (backed by fake Google services) and the real derivers, together with a deterministic `HeuristicLLM`. Tests check code-computed output, plus what the model was shown (`llm.saw(...)`) for LLM-written facts.

## 2026-10-01
- Started v1 from scratch (v0 shelved at `~/code/archie-v0`).
- Decided: files are the source of truth, SQLite is only an index, the fence rule, the LLM extracts and code checks every quote, `archie ask` is the one entry point, the TUI hosts sync with a catch-up on launch, first sync goes back 14 days and nothing is pruned, Slack waits for phase 2.
- `me.yaml` gains `legal_name` and name `aliases` (whole-word match) so mentions by name resolve to the user.
- Added the OKF bundle (describes Archie itself) and graphify (gitignored), both refreshed before every commit.
