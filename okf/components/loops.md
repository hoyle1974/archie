---
type: Component
title: Open loops
description: Detect, deduplicate, close and rank asked_of_me, i_promised and waiting_on loops.
resource: archie/derive/loops.py
status: active
tags: [component]
---

Closing needs cited evidence or the user's word. Noise rules are explicit config. Ranking is a formula in code with explanations. Design: [DESIGN §6](../../docs/DESIGN.md#6-open-loops). Vignettes C, D, H.

Implementation (`archie/derive/loops.py`):
- `derive_loops(ctx, paths)` runs once per changed Gmail thread, and only on messages it hasn't seen before. The last message seen per thread is stored in `state/loops_seen.yaml`.
  1. Messages that are bulk, inbound but not personal, or from muted senders never reach the LLM. Messages from addresses the user has never emailed are labeled "first contact", and the prompt skips optional invitations from them (cold recruiting or sales, "reply if interested").
  2. If the thread has open loops, `loops_close` (fast model) asks whether the NEW messages close them. A loop is marked `done` only with a verified quote from a new message, and only if the user hasn't set its status already.
  3. `loops_extract` (fast model) proposes candidates. Code then enforces that the cited message is new, that the quote is verbatim, and that the kind matches the direction (`asked_of_me` must cite someone else's message; `i_promised` and `waiting_on` must cite the user's own). The counterpart is taken from the headers and resolved to a dossier, and the id is deterministic from thread, message, kind and quote.
  4. The due date comes from `due_in(quote, sent)` in `archie/derive/dates.py`, never from the model (DESIGN §6.2 step 5). Jira asks and meeting-note action items use the same function, anchored to the comment time or the time the notes were given.
  5. An LLM error leaves the thread unseen so the next cycle retries it.
- Each loop is a file at `loops/<YYYY>/<loop_id>.md` with the frontmatter from DESIGN §6.4, plus `counterpart_name`, `thread` and `addressed`. The fenced section holds its history.
- `rank(loops, now, config)` computes a score and the reasons behind it. Overdue or due within 2 days, the kind, age (0.25 per day, capped at 10 days) and To-versus-Cc all count. The weights live in `config.loops.weights`. Snoozed loops come back on their date. A loop more than 7 days past due is marked `stale` ("was due …: still needed?"). It is left out of next, the Feed and briefings, and `loops` lists it under "Maybe already done?".

Intents (`archie/ask/intents/loops.py`):
- `loops` lists open items ranked by code, with no LLM call. "waiting" narrows the list to `waiting_on`, and "owe" or "promised" removes `waiting_on`. Each line cites its source quote.
- Noise rule: the second dismissal of items from the same counterpart adds their email to `loops.mute` in `config.yaml` and tells the user how to undo it. Mail from muted senders (an exact email or an `@domain`) never reaches extraction.
- `loop_update` uses the fast model to match "done with Sarah's question", "snooze till Monday" or "that's not a loop" to the numbered items, then applies the change in code. A loop closed this way records `closed_by: {user: "said done <date>"}`.

Cross-channel closure (`archie/derive/cross_close.py`) runs as the last deriver.
- For each open `asked_of_me` or `i_promised` loop, the candidates are the user's own [activity](activity.md) since the loop opened that shares a content word with its summary, excluding the loop's own thread. The top 5 are kept.
- The fast model (`loops_cross`) judges them. A verified "strong" match sets the loop to `done`, and a "weak" one sets `maybe_done`. Either way `closed_by` cites the evidence.
- `state/cross_checked.yaml` makes sure a loop is only checked again when newer activity exists.
