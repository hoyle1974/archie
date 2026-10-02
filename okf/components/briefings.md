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
2. Two people plus a recurring series means `one_on_one`.
3. At least `all_hands_min_attendees` (25) means `all_hands`.
4. A title containing standup, daily or scrum means `standup`.
5. A title containing all-hands, town hall or QBR means `all_hands`.
6. Otherwise `standard`.
