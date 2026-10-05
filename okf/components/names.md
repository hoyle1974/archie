---
type: Component
title: Name matching
description: One way to compare names everywhere (case, curly quotes, edge punctuation, possessives like "Workperson's" and "Workpersons").
resource: archie/names.py
status: active
tags: [component]
---

- `name_key` lowercases, straightens quotes and drops a trailing `'s` / `'`; `name_forms` adds the form without a trailing s for a single word ("workpersons" → "workperson", but "Priya S" stays as said). The extra forms only widen what counts as said; they never add a name.
- Used by the understanding call's grounding check ([ask](ask.md)) and by `PeopleDirectory.find` / `mentioned_in` ([derivers](derivers.md)).
- Why: "What is Workpersons title?" lost Workperson because grounding needed "workperson" as a whole word (review 2026-10-04).
