---
type: Component
title: Name matching
description: One way to compare names everywhere (case, curly quotes, edge punctuation, possessives like "Workperson's" and "Workpersons").
resource: archie/names.py
status: active
tags: [component]
---

- `name_key` lowercases, straightens quotes and drops a trailing `'s` / `'`; `name_forms` adds the form without a trailing s for a single word ("workpersons" → "workperson", but "Priya S" stays as said). The extra forms only widen what counts as said; they never add a name.
- Used by the understanding call's grounding check ([ask](ask.md)) and by `PeopleDirectory.find` / `mentioned_in` ([derivers](derivers.md)). Those two accept only apostrophe possessives ("Workperson's") by default: a bare trailing s may be someone else's name ("Andreas" isn't Andrea's), so it is a guess, allowed only with `loose=True`. Code that writes (remember, corrections, ignore) never guesses; `who` guesses last and says so ("I took priyas to mean Priya Sharma.").
- `near(a, b)`: one typo apart (a letter added, dropped or changed, or two neighbours swapped), both at least 4 letters. `PeopleDirectory.near` uses it for names and first names; it's a guess, used only by `brief` when nothing else matched, and said out loud ("I took WorkPersoon to mean Workperson Acorn.").
- Why: "What is Workpersons title?" lost Workperson because grounding needed "workperson" as a whole word (review 2026-10-04).
