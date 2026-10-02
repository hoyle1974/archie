---
type: Component
title: Derivers
description: Turn changed raw files into derived notes: meetings, people, loops, projects.
resource: archie/derive/
status: active
tags: [component]
---

Idempotent. Write only inside fences ([fence rule](../principles/fence-rule.md)). Extraction goes through [llm](llm.md). Loop logic lives in [loops](loops.md). Design: [DESIGN §5.2](../../docs/DESIGN.md#52-derivers).

- `registry.py`: `all_derivers()` returns the derivers in the order they run, and `rederive(ctx)` replays all of them over every raw file (`archie admin rederive`).
- `people.py`: builds and updates dossiers in `people/<entity_id>.md`.
  - Who gets a dossier: anyone you emailed, unless it's a role address like noreply@, support@ or unsubscribe@. Also anyone who wrote to you directly (To or Cc) with mail that Gmail filed as `CATEGORY_PERSONAL`, or with no category at all, and that isn't from a role address.
  - Who doesn't: transactional "Updates" mail, newsletters, and people cc'd on inbound mail. These rules took the real archive from 48 dossiers (mostly businesses) down to 16 people.
  - What Archie owns: creating the file, appending `aliases` (the email address is always one), keeping `first_seen`/`last_interaction`/`status` current, the fence, and upgrading a `name` that was only an email placeholder. Everything else belongs to the user.
  - `PeopleDirectory`: `by_email` is an exact match. `find(name)` tries a full name or alias, then a first name, and returns every match so the caller can ask which one was meant.
- `meetings.py`: creates one note per calendar occurrence with at least one other non-resource attendee, at `meetings/<YYYY>/<YYYY-MM-DD>-<slug>.md`. All-day events and solo blocks are skipped.
  - The note is found again by `event_id`, so renaming an event keeps the same file. Archie owns the frontmatter (`event_id`, `series_id`, `title`, `start`, `end`, `type`, `attendees`, `attendee_names`, `linked_docs`, `status`, `link`) and the Decisions/Action items fence. `## My notes` belongs to the user.
  - Attendees become `stub` dossiers. A future meeting never pushes `last_interaction` past now.
  - Cancelled events set `status: cancelled`.
- `github_loops.py`: builds loops from structured data, with no LLM. An open PR that requests the user's review becomes an `asked_of_me` loop ("Review PR #n: title") whose counterpart is the author, resolved through a `gh:` alias if one exists. It closes when the user submits a review (citing that review's chunk) or the PR is merged or closed.
- `people.link_github`: adds a `gh:<login>` alias to a dossier when the PR author's public GitHub profile name matches exactly one person's name. It runs after the cycle's dossiers are created and never guesses when the match is ambiguous. `PeopleDirectory.identifiers(id)` (emails plus `gh:` logins) is what history lookups match against.
- `projects.py`: one note per GitHub repo and per Jira project at `projects/<slug>.md`. Aliases are the repo's full and short names, or the Jira key, and the user can add more ("auth redesign"). The fence holds the 15 most recent events (commits, PRs and issues with their state, Jira issues with status), computed by code. The `handover` intent searches using these aliases.
