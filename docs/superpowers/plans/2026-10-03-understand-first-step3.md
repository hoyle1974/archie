# Understand First, Step 3: Instructions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instructions run through one action list whose confirmations are written by code from what actually ran; sending is refused plainly; anything Archie can't do yet gets "I can't … yet. I've saved that you want it." and is recorded as a gap; tellings in the same message are saved and said first. Vignette P passes.

**Architecture:** A new `archie/ask/actions.py` holds `ACTIONS` (action name → `fn(ctx, part, message, last) -> Answer`), the loop-item code moved out of the `loop_update` intent (the understanding call now decides the action; the fast model only picks which items), `cant_do` for `action: none`, and `compose_cant` that orders and merges replies when a message has something Archie can't do. `remember`, `correct` and `clarify` stop being intents and move to `archie/ask/remember.py`, `correct.py`, `clarify.py` as plain functions. `dispatch.py` sends every `instruct` part through `ACTIONS`.

**Tech Stack:** Python 3.11+, pytest, line-format `Shape`, `FakeBackend`, `HeuristicLLM`.

**Spec:** `docs/superpowers/specs/2026-10-03-understand-first-design.md` §4 (build step 3 of §6).

## Global Constraints

- Confirmations for instructions are built only from what the action code did. The model never writes "done", "sent" or "snoozed".
- The understanding call's `action` decides what happens to open items; the item-picking model call only returns item numbers (and a date if the understanding call had none).
- `action: send` → exactly `I can't send anything; I only read.` Never saved as a wish.
- `action: none` (or a missing/unknown action) → `I can't <wanted> yet. I've saved that you want it.`; if `wanted` is missing or over 12 words: `I can't do “<the part's text>” yet. I've saved that you want it.` Saved in `journal/told.md` with `→ can't do this yet`.
- Both `send` and `none` parts are recorded in the usage log's `gaps` list (with step 2's `other` tellings).
- When a message has a `send` or `none` part, `tell` parts are answered first; an `other` telling's reply becomes `I saved that <its words>.` If every reply is one line, they are joined into one line.
- The help menu is never the reply to a `tell` or `instruct` part.
- Loop confirmations read `<Verb>: <who>, <summary>.` with snooze dates said as a weekday within the next six days ("Monday"), otherwise "Mon, Oct 12".
- Tests are rewritten to the new shapes and module paths; no adapters.

## Review Focus

- An instruction whose action is missing or not on the list must get the "can't … yet" reply, never the help menu or a search answer. → Task 2.
- A snooze with no date from either the understanding call or the picker must ask "Until when?" and change nothing. → Task 1.
- `reopen` must pick from closed items, the others from open ones; a pick outside the list changes nothing. → Task 1.
- A `wanted` phrase over 12 words, or containing a line break, falls back to quoting the part's words. → Task 2.
- A message with a person telling (multi-line reply) plus a `send` part keeps both replies, telling first. → Task 2.

---

### Task 1: The action list and loop actions

**Files:**
- Create: `archie/ask/actions.py`, `archie/ask/remember.py` (moved), `archie/ask/correct.py` (moved), `archie/ask/clarify.py` (moved)
- Delete: `archie/ask/intents/remember.py`, `archie/ask/intents/correct.py`, `archie/ask/intents/clarify.py`
- Modify: `archie/ask/intents/loops.py` (drop `loop_update`, `_apply`, `_maybe_mute`, `UPDATE_SHAPE`), `archie/ask/intents/__init__.py`, `archie/ask/dispatch.py`, `archie/ask/tell.py`, `archie/ask/pipeline.py`, `archie/llm/prompts/loop_update.md`, `tests/support/heuristic_llm.py`
- Test: `tests/unit/test_actions.py` (new), `tests/unit/test_loop_intents.py`, `tests/unit/test_shapes.py`, `tests/unit/test_ask.py`, `tests/unit/test_people_context.py`

**Interfaces:**
- Produces:
  - `actions.ACTIONS: dict[str, Callable[[Ctx, Part, str, dict | None], Answer]]` with `loop_done`, `loop_snooze`, `loop_dismiss`, `loop_reopen`, `meeting_type`, `merge_names`, `notes`, `ignore`, `unignore`, `show_citation`.
  - `actions.EMPTY` (moved from dispatch; dispatch re-exports it).
  - `actions.update_loops(ctx, said: str, action: str, until: str | None = None) -> Answer`, `action` in `done|snooze|dismiss|reopen`.
  - `actions.when(day: str, today: date) -> str`.
  - `actions.UPDATE_SHAPE`: name `loop_update`, fields `loops` (int list), `until`, `reason` (no `action`).
  - `correct.correct(ctx, said) -> Answer`, `clarify.clarify(ctx, said) -> Answer`, `clarify.looks_like_answer`, `remember.remember_people`, `remember.apply_facts`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_actions.py`:
  - `when("2026-10-05", date(2026,10,1)) == "Monday"`, today → `"today"`, `"2026-10-20"` → `"Tue, Oct 20"`.
  - snooze with `until` only on the part: picker reply `{"loops": [1]}` → `"Snoozed until Monday: HeadphonesRUs, earbud pairing."`, loop snoozed to that date, and the picker prompt says "snooze".
  - snooze with no date anywhere → `"Until when? Say e.g. \"snooze that till Monday\"."`, loop unchanged.
  - picker returns nothing or an out-of-range number → "I couldn't tell which item you meant…", nothing changed.
  - reopen lists only closed items.
  - `meeting_type` reaches `correct`; `merge_names` too.
  Rewrite `test_loop_intents` snooze/dismiss tests so the understanding part carries `loop_snooze` / `loop_dismiss`; `test_shapes` imports from the new modules and `test_loop_update` parses `loops: 2; 3\nuntil: 2026-10-05\nreason: -`; `test_ask` mixed test patches `ACTIONS["loop_done"]`.
- [ ] **Step 2: Run them; expect import failures.**
- [ ] **Step 3: Implement** (moves are `git mv` plus import fixes; `update_loops` keeps `_apply` and `_maybe_mute` as they are; candidates are open items, or the last 10 closed ones for `reopen`; the prompt names the wanted action; confirmations use `_label(lp) = "<who>, <summary with first letter lowered unless an acronym>"`).
- [ ] **Step 4:** `uv run pytest -q` all pass.
- [ ] **Step 5: Commit** "Instructions run through one action list; the understanding call picks the action".

### Task 2: Can't-do replies, gaps, and tellings first

**Files:**
- Modify: `archie/ask/actions.py` (`cant_do`, `compose_cant`), `archie/ask/dispatch.py`, `archie/ask/pipeline.py`
- Test: `tests/unit/test_actions.py`, `tests/unit/test_ask.py`

**Interfaces:**
- Produces: `actions.cant_do(ctx, part) -> Answer`; `actions.compose_cant(handled: list[tuple[Part, str, Answer]]) -> list[tuple[Part, Answer]]`; dispatch labels `send->gap`, `none->gap`.

- [ ] **Step 1: Failing tests:**
  - none with `wanted="filter Today by day"` → `"I can't filter Today by day yet. I've saved that you want it."`; told line `→ can't do this yet`; usage log `gaps` has the part's text.
  - `wanted` of 13 words, or none → `I can't do “only show work stuff on weekdays” yet. I've saved that you want it.`
  - unknown/missing action → same as none.
  - send → `I can't send anything; I only read.`, nothing in told.md, gap logged.
  - `tell(other) + instruct(send)` in either order → `"I saved that the pizza's picked up. I can't send anything; I only read."`
  - `tell(person) + instruct(none)` → telling reply first, then the can't line, separated by a blank line.
  - no help text in any of these replies.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** full suite green.
- [ ] **Step 5: Commit** "Can't-do replies come from code, are saved as wishes, and tellings are said first".

### Task 3: Vignette P, docs, OKF

- [ ] `tests/vignettes/test_p_cant_yet.py`: both vignette messages end to end (exact replies, told.md lines, gaps, no help text, one model call each).
- [ ] VIGNETTES row P ✅; DESIGN §8 paragraph on instructions (the action list, code-written confirmations); spec §4.4 "Added while building step 3" (picker returns only items; loop confirmation wording; joined one-line replies).
- [ ] OKF `ask.md` (actions.py, moved modules, dispatch), `loops.md` (item updates now an action), `log.md`; `okf_check` clean.
- [ ] Full suite; commit "Vignette P passes: instructions and what Archie can't do".
