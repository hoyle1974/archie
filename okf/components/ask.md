---
type: Component
title: Ask
description: The one user entry point. It routes a question to an intent, retrieves a context packet, has the LLM write an answer, verifies the citations, and renders readable output.
resource: archie/ask/
status: active
tags: [component]
---

- `pipeline.py`: `ask(ctx, question) -> Answer` calls `route`, then the intent's handler. An unknown intent falls back to `search`.
- `router.py`: classifies the question with the `fast` model into an intent with parameters (people, since/until, topic, meeting, text). It states no facts, so it needs no citations. The intent list lives in `INTENT_HELP`.
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

Intents still to build: next, ledger, handover, notes, catchup, correct. Design: [DESIGN §8](../../docs/DESIGN.md#8-archie-ask). Principles: [one entry point](../principles/one-entry-point.md), [readable first](../principles/readable-first.md).
