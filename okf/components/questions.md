---
type: Component
title: Audit and clarifying questions
description: After each sync, finds confusion in new data and turns it into a few clarifying questions the user answers in plain English. Duplicate people are part of this.
resource: archie/derive/audit.py
status: active
tags: [component]
---

- `audit` (`audit.py`) runs after every sync as a post-index step, with no LLM. At most `MAX_OPEN` (5) questions are open at once, most important first:
  1. `same_person`: two dossiers that are probably one person.
  2. `loop_done`: "Did you finish …?" for a `maybe_done` loop. Yes closes it; no reopens it and clears `closed_by`.
  3. `loop_stale`: "Do you still need to …?" for a loop more than a week past due. Yes keeps it and clears the due date; no closes it.
  4. `waiting_nudge`: "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?" for an open `waiting_on` loop (or one whose snooze has ended) at least `nudges.after_days` (default 3) whole days old, from a Gmail thread with no message from the counterpart (their address, or their domain) after `created_at`. Checked in code against the thread's raw file. It resolves itself when they reply or the item closes. Its id includes the item's `snoozed_until`, so a nudge answered with a snooze can come back once the snooze ends with still no reply. Replies are handled by [ask](ask.md) (`actions.answer_nudge`).
  5. `who_is`: "Who is x@y?" for someone you correspond with who is known only by an address. The user answers by telling Archie about them (the `remember` code) or by saying to ignore them. The question resolves itself once a name, relationship or role exists, or once the sender is ignored; ignored senders are never asked about.

  Questions answered some other way, such as a loop closed by hand, resolve themselves right away: `resolve_answered` runs after every answer and before Today is drawn, with no model call.
- `find_duplicates` (`dedupe.py`) is called by the audit.
  - The same full name (two or more words) plus the same email username at different domains is merged automatically, and a "notice" shows in Today for 24 hours. A name alone never merges, since two people can share one.
  - Weaker evidence becomes a `same_person` question: the same full name alone, names where one contains the other (same first and last name), a shared multi-word alias, or the same email username and first name.
- Questions live in `state/questions.yaml`. Answered ones are kept, so a "no" is never asked again.
- `merge_people` (in `people.py`) folds one dossier into another and re-points loops and meetings. It merges aliases, the user's notes, cited facts and relationship, role and pronouns. The other file stays, marked `status: merged`.
- `archie/ask/clarify.py` handles replies (through `tell.answer_yes_no`, which also saves them in `journal/told.md`). A plain yes or no to a single open yes/no question needs no model. With several open, the fast model maps the reply to question numbers, and `audit.answer` applies it. `ask` sends any yes/no-shaped reply here whenever such questions are open.
- The Today pane lists up to 3 open questions under "Archie has a question" and recent notices under "Recently".

See [derivers](derivers.md) and [ask](ask.md).
