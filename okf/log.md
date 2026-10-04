---
type: Log
title: Archie change log
description: Chronological history of design decisions and structural changes, newest first.
---

## 2026-10-03
- The model backend is now Gemini (`google-genai`), and replies use a plain line format instead of JSON schemas (`archie/llm/shape.py`). Each call declares a `Shape`; code writes the format instructions, parses and checks the reply, and retries once. Schema-forced JSON cost tokens and was less reliable. The Claude backend is removed (it's in git history). Spec: `docs/superpowers/specs/2026-10-03-gemini-line-format-design.md`.
- Gemini live check: `gemini-3.7-flash` (fast) and `gemini-3.1-pro-preview` (strong) both answered. A cited search answer kept 4 claims and dropped 2 whose quotes were real but credited to the wrong source; a who answer dropped none; `remember` saved Sam. Measured cost: about 3–4¢ per strong-tier answer (mostly Pro thinking tokens), about 0.2¢ per fast call. Found and fixed: used-up prepaid credits (HTTP 402) were reported as a rate limit, and the SDK printed an automatic-function-calling warning.
- Written answers (the `strong` tier) now use `gemini-3.7-flash` instead of `gemini-3.1-pro-preview`. On the same two questions Flash dropped no claims (Pro dropped 2 on one), answered in about 10 seconds instead of 20, and cost about 1.3¢ instead of 3–4¢.
- Sync reports what it's waiting on (`on_progress`): the sources still running, then the deriver, index or final-check step. Derivers now run in a worker thread so the TUI keeps redrawing while they call the model.
- People with the same full name are no longer merged on the name alone. A merge now also needs the same email username, and otherwise Archie asks. Two different people with one name would have been folded together, with no way to undo it.
- Sync orders connectors with `graphlib.TopologicalSorter` instead of a fixed two-wave split, so `after` chains of any depth work.
- Due dates are parsed by code from the verified quote (`archie/derive/dates.py`) for email, Jira and meeting-note loops. Before this, the model's date was used, which broke DESIGN §2.5. The model's schema no longer has `due`.
- Vignette tests now check what the user sees: rebuilding once after an edit (A), names and emails resolving to one person and ambiguous names (B), the same ask in email and Jira (C), "next Wed" in notes (H), and open items with the person (J). Parts that aren't built yet are strict `xfail` tests, and A, B, C and J are back to 🟨.
- DESIGN: the intent table lists `remember` and `clarify`. The example dossier no longer stores recent interactions, matching §5.2.

## 2026-10-02
- Drafted the design for `now` as a source (`docs/superpowers/specs/2026-10-02-now-source-design.md`). Waiting on the auth choice; no code yet.
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
