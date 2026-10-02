---
type: Component
title: Questions and duplicates
description: Spots people who are probably the same, merges the obvious cases, and asks about the rest through clarifying questions the user answers in plain English.
resource: archie/derive/dedupe.py
status: active
tags: [component]
---

- `find_duplicates` runs as a post-index step with no LLM.
  - The same full name (two or more words) under different addresses is merged automatically, and a "notice" shows in Today for 24 hours.
  - Weaker evidence becomes a `same_person` question: names where one contains the other (same first and last name), a shared multi-word alias, or the same email username at different domains.
- Questions live in `state/questions.yaml`. Answered ones are kept, so a "no" is never asked again.
- `merge_people` (in `people.py`) folds one dossier into another and re-points loops and meetings. It merges aliases, the user's notes, cited facts and relationship, role and pronouns. The other file stays, marked `status: merged`.
- The `clarify` intent handles replies. A plain yes or no to a single open question needs no model; with several open, the fast model maps the reply to question numbers. The router sends any yes/no-shaped reply here whenever questions are open.
- The Today pane lists up to 3 open questions under "Archie has a question" and recent notices under "Recently".

See [derivers](derivers.md) and [ask](ask.md).
