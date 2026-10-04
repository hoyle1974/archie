---
type: Component
title: Ask
description: The one user entry point. It understands each message (with the recent conversation and open questions) into parts, sends each part where it belongs, retrieves a context packet for questions, has the LLM write an answer, verifies the citations, and renders readable output.
resource: archie/ask/
status: active
tags: [component]
---

- `pipeline.py`: `ask(ctx, question) -> Answer`. Code-only shortcuts first (quick questions, "show N", "really?", a plain yes/no to one open question), then `understand`, then `dispatch` for every part. In a mixed message, cited replies are merged into one answer (each later part under a heading with its words) so one numbering covers every `[n]` and source; plain replies are joined as text. Each exchange is appended to `state/conversation.jsonl` (see `conversation.py`) and to `logs/usage.jsonl` (local and gitignored) with the handler of each part, whether a shortcut was used, ms, nothing_found, dropped claims, the answer as shown and any error.
- `understand.py`: one fast-tier call (`understand` shape, `PART` records) splits the message into question, tell, instruct, answer and unclear parts. `checked` enforces: a part's words must be in the message (a single part always gets the whole message), a rewritten question (`resolved`) and an ask-back may only use name-like words that are whole words someone said (the message, the recent exchanges or the open questions), a person is kept only if someone said part of their name, an answer must point at a real open question, and `text`/`notes` hold only a first line so pasted notes never come back in the reply. `QUESTION_INTENTS` lists the intents a question can have.
- `dispatch.py`: questions go to their intent (unknown ones to `search`, on the rewritten question when there is one). Until build steps 2–3: tellings and "Who is …?" answers go to `remember`, yes/no answers to `clarify`, instructions to `loop_update`, `correct` or `notes`; `send` gets "I can't send anything; I only read." and anything else "I can't do that yet."; unclear parts ask back.
- `conversation.py`: the last 200 exchanges (`said`, `resolved`, `summary`, numbered `citations`). `recent` returns up to 3, oldest first, ended by a 30-minute gap.
- `followup.py`: "show N" prints citation N of the last answer (label, quote, the text around it, then the path) with no model call; "really?" re-asks the last question and says when the answer changed, but only when the last exchange was all questions (or a "show N" about one), so a telling, notes or a yes/no answer is never redone. Each conversation entry records its part `kinds` for this. A "show" with no clear number asks which source.
- `router.py`: `quick_route` handles unambiguous, parameter-free questions in code ("what's next?", "what do I owe people?", "help") and skips the model call.
- `synthesize.py`: `people_context` adds what the user has told Archie (relationship, identity, pronouns, role) about every known person the packet mentions, and tells the model it overrides the sources, so an email saying "my son" can't override "my child". Then it sends the packet to the `strong` model, which returns `{summary, sections}` made of claims, and runs every claim through the [verifier](llm.md).
- `answer.py`: `Answer` holds the summary claims, sections (cited items plus lines computed by code), the packet, the count of dropped claims, plain text, notes, and a `nothing_found` flag.
- `render.py`: puts the summary first and numbers `[n]` markers in the order they appear. The source list is shown only with `--sources`. It says plainly when nothing was found or nothing could be verified.
- `intents/`: each one registers with `@intent(name)`.
  - `search`: hybrid search plus synthesis.
  - `help`: fixed text, no LLM.
  - `who`: resolves a person through `PeopleDirectory`, asks back if the name is ambiguous, and says so if the person is unknown. Code computes the "At a glance" facts (org, role, last talked, thread count) and the "Recent" list from `Index.chunks_with_people`. On top of that, the LLM writes a cited summary drawn from the dossier and recent mail.
- `context.py`: `Ctx` bundles home, config, me, index, backend and now, so tests can swap any part.

  - `agenda`: lists what's on the calendar for a day or range, read from the calendar mirror with no model: all-day events first, then timed ones, with meetings showing who's in them. Declined and cancelled events are left out, and an event on two calendars is shown once. "today", "tomorrow", "this weekend" and weekday names are parsed by code and quick-routed; anything else uses the understood since/until.
  - `brief`: see [briefings](briefings.md). Personal events (no attendees) are never briefed.
  - `loops` and `loop_update`: see [loops](loops.md).
  - `notes`:
    - Finds the matching meeting: a recent one (from 24 hours ago to 1 hour ahead) that matches by title words. With no meeting named, it takes the most recent one.
    - Appends the text word for word, with a timestamp, under `## My notes`. Notes for nothing on the calendar become a standalone `notes_only` meeting file.
    - Extracts action items (fast model, `notes_actions`) and keeps only those whose quotes verify against the note. The user's own items become `i_promised` loops and other people's become `waiting_on` loops, each citing the meeting file. Due dates ("by next Wed") are parsed by code from the quote, relative to when the notes were given, and shown as "due Wed, Oct 7".
    - Writes the list into the meeting's Action items fence.

  - `next`: computed entirely in code. It works out the free time before the next meeting today, ranks loops (boosting anyone you meet today) under "Do next", and lists `waiting_on` items 3 or more days old under "Nudge". No LLM call.

  - `correct`: the fast model classifies the correction, and code applies it to files the user can see. A meeting type writes an override to `config/meeting_types.yaml` (by series id, or by exact title if there is no series) and re-types existing meeting notes. "X is Y" adds an alias to Y; if X is a separate dossier, it is merged into Y because the user said so, and marked `status: merged`. A role sets `role` on the dossier.

  - `ledger`: the window comes from the understood since/until and defaults to this week (Monday until now).
    - The summary line counts each kind of activity.
    - Up to 31 days, items are listed by kind. Longer windows group them by project (repo, Jira project or docs).
    - Every item cites its source chunk, and no LLM is involved.
    - `write_week_journal` writes `journal/weekly/<YYYY>-W<ww>.md` with the ledger inside the fence. The tick runs it on Fridays from 3 PM.

  - `remember`: the user tells Archie about one or more people ("Goodspouse is my wife, she goes by Belle", "Acorn is my youngest, he's three").
    - Code sets `relationship`, `role`, `pronouns`, `identity`, `avoid` (words never to use for them) and aliases on the dossier, creating a `status: known` dossier for someone with no email history.
    - Each person's sentence goes word for word under `## My notes`, but only if it really appears in the message.
    - `who` shows "Your <relationship> · pronouns" and passes pronouns to the model. "my family" lists dossiers whose relationship is a family word. Briefings show the relationship too.
  - `catchup`:
    - The window comes from since/until and defaults to the last 7 days.
    - The packet is up to 30 chunks from that window, limited to gmail, github, jira, drive and meetings. Gmail chunks count only from personal, non-bulk messages.
    - Code lists "Opened while you were out" (loops created in the window) and "Meetings in that window" (marked when they have notes). The LLM summarizes decisions and changes.
  - `handover`:
    - Searches for the project name plus any aliases from `projects/<slug>.md`, and finds loops that mention it.
    - Code counts the people involved. The LLM writes cited Current state, Key decisions, Open issues, and Risks and tech debt.
    - Saved to `projects/<slug>-handover-<date>.md`.

Every intent in DESIGN §8 is now built. Design: [DESIGN §8](../../docs/DESIGN.md#8-archie-ask). Principles: [one entry point](../principles/one-entry-point.md), [readable first](../principles/readable-first.md).
