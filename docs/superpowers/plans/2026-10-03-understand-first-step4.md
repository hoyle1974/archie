# Understand First, Step 4: "Which one did you mean?" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When more than one thing fits, Archie asks "Which one: A or B?" instead of guessing, remembers the question for the next message, applies a short reply ("Workpersonthree's", "the first one", "2") to the right item, and lets the question lapse after 30 minutes or any other message. Vignette Q passes.

**Architecture:** A new `archie/ask/which.py` writes the question (`ask_which`), matches a reply to the options in code (`match`), and runs the original request on the chosen option (`resolve`). `Answer` gets a `pending` field; the pipeline saves it in the conversation entry. Two producers: the loop-item picker (`update_loops`) when the user means one item and several fit (new `one` field on the `loop_update` shape), and the understanding call's `unclear` part when its `options` are numbers of Archie's open questions. The pipeline tries `match` on the next message (within the 30-minute window) right after "show N"; otherwise the understanding call sees the pending question and may return `PART answer` with `options: <n>`, which dispatch resolves.

**Tech Stack:** Python 3.11+, pytest, line-format `Shape`, `FakeBackend`.

**Spec:** `docs/superpowers/specs/2026-10-03-understand-first-design.md` §5.1 (build step 4 of §6).

## Global Constraints

- The question is written by code from the options; options are validated (loop ids that exist, or open-question numbers in range).
- A pending question lives only in the newest conversation entry: the next message either answers it or drops it. After 30 quiet minutes it's gone (`conversation.recent` is empty).
- Code matching comes before any model call: a bare number ("2", "#2", "number 2"), an ordinal ("the first one", "second", "last"), or words that all point to one option (a word counts if it is in exactly one option's label; "Workpersonthree's" counts as "workpersonthree").
- The chosen option runs the original request: for loop actions, the same action (with the same date or reason) on that one item, confirmed by code; for open questions, the original answer applied to that question.
- If the chosen item was closed meanwhile, say so and change nothing.
- No new command; files stay the source of truth (the pending question is in `state/conversation.jsonl`).

## Review Focus

- A reply that matches no option by code and isn't an `answer` part from the model must not apply anything, and the pending question must not survive into the following exchange. → Task 2.
- A word shared by two options ("pizza" in both) must not pick either. → Task 1.
- An `answer` part with `options` outside the pending list, or with no pending question, must be treated as a question, not resolved. → Task 2.
- A snooze chosen through "which one" keeps the date from the original message. → Task 1.

---

### Task 1: `which.py` and the loop picker asks back

**Files:** Create `archie/ask/which.py`; modify `archie/ask/answer.py` (`pending`), `archie/ask/actions.py` (`one` field, `_finish`, pending for loops), `archie/llm/prompts/loop_update.md`; test `tests/unit/test_which.py`.

**Interfaces:**
- `which.ask_which(labels: list[str]) -> str` → "Which one: A or B?" / "Which one: A, B or C?"
- `which.match(text: str, labels: list[str]) -> int | None` (0-based)
- `which.resolve(ctx, pending: dict, index: int) -> Answer`
- pending dict: `{"kind": "loops", "action", "until", "reason", "options": [{"label", "id"}]}` or `{"kind": "question", "text", "fact", "options": [{"label", "id"}]}` (id = loop id or open-question id).
- `actions.UPDATE_SHAPE` gains `F("one", "bool", required=False)`; `actions.finish_loops(ctx, action, loops, until, reason) -> Answer`.

- [ ] Tests: `ask_which` for 2 and 3 labels; `match` by number, "#2", "number 2", ordinals ("the first one", "second", "last"), a unique word ("Workpersonthree's"), a shared word ("pizza") → None, an out-of-range number → None, unrelated text → None; picker returning two items with `one: yes` → "Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?", nothing changed, `answer.pending` holds both loop ids; with `one` empty both are applied; `resolve` on a loops pending marks only the chosen one and keeps a snooze date; `resolve` on an item closed meanwhile → "That one is already closed." and nothing changes.
- [ ] Implement; full suite green; commit "Which one: the loop picker asks back instead of guessing".

### Task 2: Pending questions in the conversation, and the next message

**Files:** modify `archie/ask/pipeline.py`, `archie/ask/understand.py` (`prompt_input` and `checked` take `pending`), `archie/ask/dispatch.py`, `archie/llm/prompts/understand.md`; tests in `tests/unit/test_which.py`, `tests/unit/test_understand.py`.

- [ ] Tests: the conversation entry stores `pending`; "Workpersonthree's" next resolves with no model call; after 31 minutes "Workpersonthree's" does not resolve (goes to the understanding call, nothing changes); an unrelated message drops the pending question (the one after it can't answer it); the understanding call sees "Archie asked: Which one…" with numbered options; `PART answer` + `options: 2` resolves option 2; `options: 5` (out of range) or no pending → treated as a question; `unclear` with `options: 1; 2` naming open questions writes "Which one: …?" from code and saves a question pending; resolving it applies the original answer to that question.
- [ ] Implement; full suite green; commit "Pending which-one questions are saved and answered by the next message".

### Task 3: Vignette Q, docs, OKF

- [ ] `tests/vignettes/test_q_which_one.py`: Workpersonthree and Workpersonfour items; "she's done with it" → exact question, nothing changed; "Workpersonthree's" → "Marked done: Workpersonthree, pizza instructions.", only Workpersonthree's closed, no model call for the reply; a second run where the reply comes 31 minutes later changes nothing.
- [ ] VIGNETTES Q ✅; DESIGN §8 sentence on asking back; spec §5.3 "Added while building step 4"; OKF `ask.md` (which.py, pending), `log.md`; okf_check; commit "Vignette Q passes: Archie asks which one".
