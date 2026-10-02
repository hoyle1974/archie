---
type: Log
title: Archie change log
description: Chronological history of design decisions and structural changes, newest first.
---

## 2026-10-02
- Fixes from the first real use of the TUI:
  - Sync failed with "bad value(s) in fds_to_keep" because tqdm's multiprocessing lock can't spawn under Textual. tqdm now gets a thread lock.
  - Copying didn't work because macOS Terminal ignores OSC 52. Copying now also uses `pbcopy`, and Ctrl+Y copies the answer.
  - Added the single-writer lock that DESIGN §3.1 called for.
- M4 is done: all 13 vignettes have passing end-to-end tests (`tests/vignettes/`). Added the catchup and handover intents. All-hands briefings were already handled by the meeting-type template.
- M3 is done. Vignettes C, D, E, F and M pass, and A passes for standard meetings, 1:1s and standups. Added GitHub (live through `gh`) and Jira (fakes only), GitHub review-request loops, cross-channel closure, the activity module, the ledger, the weekly journal and code-computed standup sections.
- Classifier change: an explicit title keyword (standup, all-hands) now wins over structure, so a 2-person "Daily Standup" stays a standup.
- A loop more than 7 days past due is marked "still needed?". The live archive showed a long-overdue item ranking as most urgent.
- GitHub logins join a dossier automatically when the public profile name matches exactly one person.
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
