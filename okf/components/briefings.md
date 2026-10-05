---
type: Component
title: Briefings
description: Meeting type resolution (no LLM), per-type retrieval templates, morning batch plus a T-15 refresh and notification.
resource: archie/briefings/
status: active
tags: [component]
---

Types: one_on_one, standup, all_hands, standard. Includes conflict callouts. Uses [index-search](index-search.md), [loops](loops.md), [llm](llm.md). Design: [DESIGN §7](../../docs/DESIGN.md#7-briefings). Vignettes A, L, M.

Built so far: `classify.py`, which picks the meeting type in code. Checked in order:
1. The user's overrides in `config/meeting_types.yaml`, by `series` id or exact `titles`.
2. A title containing standup, daily or scrum means `standup`.
3. A title containing all-hands, town hall or QBR means `all_hands`.
4. Two people plus a recurring series means `one_on_one`.
5. At least `all_hands_min_attendees` (25) means `all_hands`.
6. Otherwise `standard`.

Keywords come before structure, so a 2-person "Daily Standup" is still a standup.

- `build.py`:
  - `upcoming(ctx)` lists scheduled meetings that haven't ended, from now to 36 hours ahead.
  - `pick_meeting(ctx, text)` chooses one: "next" (or nothing) means the soonest, "2pm"/"4:30" matches the start time, and anything else matches title words.
  - `build_briefing(ctx, meeting)`:
    - Builds a packet from the event chunk plus a template for the meeting type. 1:1s add the previous occurrence's note and limit everything to activity since then. Standard meetings and 1:1s add attendee dossiers and up to 12 of each attendee's passages since the window start from the evidence selector ([ask](ask.md) `person_evidence`), so mail they sent comes before newer threads they were only copied on. Standups use the last 3 days of activity. Every type adds a hybrid search on the title, but only when the title has at least 2 real words, because a one-word title like "Test" matched unrelated commits.
    - The LLM writes a cited summary and sections using per-type `INSTRUCTIONS` (conflicts become a "⚠️ Conflict" item).
    - Code adds the header line ("2:00 PM · Title · 45 min"), a People section (role, last talked, or "New: no history yet (org)"), and "Open with these people", the attendees' loops ranked with the in-meeting boost.
    - The result is saved to `briefings/<date>/<HHMM>-<slug>.md` with a `packet_hash`. If the inputs haven't changed, the saved briefing is reused without an LLM call.
- `schedule.py`: `tick(ctx, notify)` runs every minute in the TUI and after every sync.
  - It builds any of today's briefings that are missing, which acts as the morning batch.
  - At T-`lead_minutes` (15) it rebuilds a briefing if its inputs changed and sends one macOS notification (`osascript`), recording `notified: true`.
- The `brief` intent (`archie/ask/intents/brief.py`) answers "prep me for my 2pm".
- The TUI Feed (`archie/tui/feed.py`) shows the next briefing, the meetings later today, and the top 3 open items.
- Standup briefings get code-computed sections. Yesterday is `my_activity` since the last working day (Monday looks back to Friday). Today is the user's In Progress Jira issues plus loops due by tomorrow. "Blockers / new asks" is `asked_of_me` loops from the last 24 hours.
