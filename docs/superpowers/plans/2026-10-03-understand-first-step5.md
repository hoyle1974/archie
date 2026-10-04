# Understand First, Step 5: Nudges — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Today shows "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?" for open `waiting_on` items with no reply after `nudges.after_days`; the user's reply snoozes, closes or dismisses the item (or waits another `after_days` for "yes, I'll follow up"), confirmed by code; the nudge clears itself when the counterpart replies or the item closes, and comes back only if a snooze ends with still no reply. Vignette R passes.

**Architecture:** `archie/derive/audit.py` gets a `waiting_nudge` kind: candidates and `_still_relevant` use a code-only `no_reply(home, loop, directory)` check on the thread's raw file. The question id includes the item's `snoozed_until`, so a nudge answered with a snooze can be asked again after the snooze ends. Replies are `answer` parts (the understanding call sets `action` on them: `loop_snooze` + `until`, `loop_done`, `loop_dismiss`, or `nudge_snooze`); `dispatch` sends answers to nudges to `actions.answer_nudge`, which applies the action with `finish_loops`, marks the question answered and saves the words in `journal/told.md`. `nudge_snooze` as a plain instruction applies to the one open nudge (or asks which).

**Tech Stack:** Python 3.11+, pytest, `FakeBackend`.

**Spec:** `docs/superpowers/specs/2026-10-03-understand-first-design.md` §5.2 (build step 5 of §6).

## Global Constraints

- Nudges come from code only: status open (or a snooze that has ended), kind `waiting_on`, at least `nudges.after_days` (default 3) whole days since `created_at`, and no message from the counterpart in the thread after `created_at`.
- Priority: `same_person`, `loop_done`, `loop_stale`, `waiting_nudge`, `who_is`; `MAX_OPEN` = 5 still applies.
- Confirmations are code-written ("Snoozed until Monday: HeadphonesRUs, earbud pairing."). Archie never sends anything; "yes, I'll follow up" only snoozes for `after_days`.
- Every answer to a nudge is saved in `journal/told.md`.

## Review Focus

- A counterpart reply after `created_at` must clear an open nudge on the next `resolve_answered`, without a model call. → Task 1.
- A nudge answered with a snooze must not come back before the snooze ends, and must come back after it ends if there's still no reply. → Task 1.
- An answer part to a nudge with no usable action (or a past date) must not change the item silently. → Task 2.
- A plain "yes" to a nudge must not be routed to `clarify`. → Task 2.

---

### Task 1: `waiting_nudge` in the audit

**Files:** modify `archie/derive/audit.py`, `archie/config.py` (`nudges.after_days`); test `tests/unit/test_audit.py`.

- [ ] Tests: a 3-day-old open `waiting_on` item with no reply gets exactly "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?"; 2 days old → none; a reply from the counterpart (or from their domain) after `created_at` → none, and an open nudge is resolved by `resolve_answered`; my own later message doesn't count; snoozed (future) → none; snooze ended with no reply → a new nudge (different id); done/dismissed → resolved; priority puts it after `loop_stale` and before `who_is`; long summaries are quoted (“Troubleshoot new earbud pairing issue”).
- [ ] Implement; full suite green; commit "Nudges: waiting_nudge questions from code".

### Task 2: Replies to nudges

**Files:** modify `archie/ask/actions.py` (`answer_nudge`, `ACTIONS["nudge_snooze"]`), `archie/ask/dispatch.py`, `archie/llm/prompts/understand.md`; tests `tests/unit/test_actions.py`.

- [ ] Tests: answer + `loop_snooze` until Monday → "Snoozed until Monday: HeadphonesRUs, earbud pairing.", question answered, told line; `loop_done` → "Marked done: …"; `loop_dismiss` → "Dismissed: …"; `nudge_snooze` or no action → snoozed `after_days` from today ("Snoozed until Sunday: …" for Oct 1 + 3); `loop_snooze` with a past or missing date → "Until when?" and nothing changes; plain "yes" with only a nudge open goes to the understanding call (not clarify); an instruct `nudge_snooze` with one open nudge applies to it, with none says "There's nothing to follow up on right now.".
- [ ] Implement; full suite green; commit "Replies to nudges snooze, close or dismiss the item".

### Task 3: Vignette R, docs, OKF

- [ ] `tests/vignettes/test_r_nudges.py`: Today shows the nudge; "I'll give them till Monday" → exact reply and the nudge is gone; a second item gets a reply from HeadphonesRUs in the thread → its nudge clears; "Yes, I'll follow up" → snoozed 3 days, comes back after with no reply.
- [ ] VIGNETTES R ✅; DESIGN (audit kinds, nudges, config `nudges.after_days`); spec §5.4 "Added while building step 5"; OKF `questions.md`, `config.md`, `ask.md`, `log.md`; okf_check; commit.
