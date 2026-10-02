---
type: Component
title: Ask
description: The one user entry point. It routes a question to an intent, retrieves a context packet, has the LLM write an answer, verifies the citations, and renders readable output.
resource: archie/ask/
status: active
tags: [component]
---

- `pipeline.py`: `ask(ctx, question) -> Answer` calls `route`, then the intent's handler. An unknown intent falls back to `search`.
- `router.py`: `quick_route` handles unambiguous, parameter-free questions in code ("what's next?", "what do I owe people?", "help") and skips the model call. Everything else is classified with the `fast` model into an intent with parameters (people, since/until, topic, meeting, text). It states no facts, so it needs no citations. The intent list lives in `INTENT_HELP`.
- `synthesize.py`: sends the packet to the `strong` model, which returns `{summary, sections}` made of claims, and runs every claim through the [verifier](llm.md).
- `answer.py`: `Answer` holds the summary claims, sections (cited items plus lines computed by code), the packet, the count of dropped claims, plain text, notes, and a `nothing_found` flag.
- `render.py`: puts the summary first and numbers `[n]` markers in the order they appear. The source list is shown only with `--sources`. It says plainly when nothing was found or nothing could be verified.
- `intents/`: each one registers with `@intent(name)`.
  - `search`: hybrid search plus synthesis.
  - `help`: fixed text, no LLM.
  - `who`: resolves a person through `PeopleDirectory`, asks back if the name is ambiguous, and says so if the person is unknown. Code computes the "At a glance" facts (org, role, last talked, thread count) and the "Recent" list from `Index.chunks_with_people`. On top of that, the LLM writes a cited summary drawn from the dossier and recent mail.
- `context.py`: `Ctx` bundles home, config, me, index, backend and now, so tests can swap any part.

  - `brief`: see [briefings](briefings.md).
  - `loops` and `loop_update`: see [loops](loops.md).
  - `notes`:
    - Finds the matching meeting: a recent one (from 24 hours ago to 1 hour ahead) that matches by title words. With no meeting named, it takes the most recent one.
    - Appends the text word for word, with a timestamp, under `## My notes`. Notes for nothing on the calendar become a standalone `notes_only` meeting file.
    - Extracts action items (fast model, `notes_actions`) and keeps only those whose quotes verify against the note. The user's own items become `i_promised` loops and other people's become `waiting_on` loops, each citing the meeting file.
    - Writes the list into the meeting's Action items fence.

  - `next`: computed entirely in code. It works out the free time before the next meeting today, ranks loops (boosting anyone you meet today) under "Do next", and lists `waiting_on` items 3 or more days old under "Nudge". No LLM call.

  - `correct`: the fast model classifies the correction, and code applies it to files the user can see. A meeting type writes an override to `config/meeting_types.yaml` (by series id, or by exact title if there is no series) and re-types existing meeting notes. "X is Y" adds an alias to Y; if X is a separate dossier, it is merged into Y because the user said so, and marked `status: merged`. A role sets `role` on the dossier.

  - `ledger`: the window comes from the router's since/until and defaults to this week (Monday until now).
    - The summary line counts each kind of activity.
    - Up to 31 days, items are listed by kind. Longer windows group them by project (repo, Jira project or docs).
    - Every item cites its source chunk, and no LLM is involved.
    - `write_week_journal` writes `journal/weekly/<YYYY>-W<ww>.md` with the ledger inside the fence. The tick runs it on Fridays from 3 PM.

  - `catchup`:
    - The window comes from since/until and defaults to the last 7 days.
    - The packet is up to 30 chunks from that window, limited to gmail, github, jira, drive and meetings. Gmail chunks count only from personal, non-bulk messages.
    - Code lists "Opened while you were out" (loops created in the window) and "Meetings in that window" (marked when they have notes). The LLM summarizes decisions and changes.
  - `handover`:
    - Searches for the project name plus any aliases from `projects/<slug>.md`, and finds loops that mention it.
    - Code counts the people involved. The LLM writes cited Current state, Key decisions, Open issues, and Risks and tech debt.
    - Saved to `projects/<slug>-handover-<date>.md`.

Every intent in DESIGN §8 is now built. Design: [DESIGN §8](../../docs/DESIGN.md#8-archie-ask). Principles: [one entry point](../principles/one-entry-point.md), [readable first](../principles/readable-first.md).
