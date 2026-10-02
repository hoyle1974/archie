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
- `intents/`: built so far are `search` (hybrid search plus synthesis) and `help` (fixed text, no LLM). Each one registers with `@intent(name)`.
- `context.py`: `Ctx` bundles home, config, me, index, backend and now, so tests can swap any part.

Intents still to build: brief, who, loops, loop_update, next, ledger, handover, notes, catchup, correct. Design: [DESIGN §8](../../docs/DESIGN.md#8-archie-ask). Principles: [one entry point](../principles/one-entry-point.md), [readable first](../principles/readable-first.md).
