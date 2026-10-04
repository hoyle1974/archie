---
type: Component
title: Derivers
description: Turn changed raw files into derived notes: meetings, people, loops, projects.
resource: archie/derive/
status: active
tags: [component]
---

Idempotent. Write only inside fences ([fence rule](../principles/fence-rule.md)). Extraction goes through [llm](llm.md). Loop logic lives in [loops](loops.md). Design: [DESIGN §5.2](../../docs/DESIGN.md#52-derivers).

- `failures.py`: when a model call fails, derivers leave the item for the next sync. `Failures` (`state/llm_failures.yaml`) counts failures caused by the item itself (an unreadable or cut-off reply, a safety block: `LLMError.about_input`) and skips the item after 3 on the same content, so one bad thread can't cost a call every sync. Quota, key, network and server errors never count. New content (a new message, comment or mention) gets a fresh start. Used by email loops, Jira loops, people facts and cross-channel closing.
- `registry.py`: `all_derivers()` returns the derivers in the order they run, and `rederive(ctx)` replays all of them over every raw file (`archie admin rederive`).
- `people.py`: builds and updates dossiers in `people/<entity_id>.md`.
  - Who gets a dossier: anyone you emailed, unless it's a role address like noreply@, support@ or unsubscribe@. Also anyone who wrote to you directly (To or Cc) with mail that Gmail filed as `CATEGORY_PERSONAL`, or with no category at all, and that isn't from a role address.
  - Who doesn't: transactional "Updates" mail, newsletters, and people cc'd on inbound mail. These rules took the real archive from 48 dossiers (mostly businesses) down to 16 people.
  - What Archie owns: creating the file, appending `aliases` (the email address is always one), keeping `first_seen`/`last_interaction`/`status` current, the fence, and upgrading a `name` that was only an email placeholder. Everything else belongs to the user.
  - `PeopleDirectory`: `by_email` is an exact match. `find(name)` tries a full name or alias, then a first name, and returns every match so the caller can ask which one was meant.
- `meetings.py`: creates one note per timed calendar occurrence. Occurrences with no other attendees get `type: event`: they appear in Today's agenda and count as busy time, but get no briefing or notification. Notes go at `meetings/<YYYY>/<YYYY-MM-DD>-<slug>.md`. All-day events are skipped.
  - The note is found again by `event_id`, so renaming an event keeps the same file. Archie owns the frontmatter (`event_id`, `series_id`, `title`, `start`, `end`, `type`, `attendees`, `attendee_names`, `linked_docs`, `status`, `link`) and the Decisions/Action items fence. `## My notes` belongs to the user.
  - `type_auto` records the type Archie chose. If `type` differs from it, the user edited the file, and their value is kept on later updates.
  - Attendees become `stub` dossiers. A future meeting never pushes `last_interaction` past now.
  - Cancelled events set `status: cancelled`, and events the user declined set `status: declined`. Only `scheduled` meetings get briefings.
- `github_loops.py`: builds loops from structured data, with no LLM. An open PR that requests the user's review becomes an `asked_of_me` loop ("Review PR #n: title") whose counterpart is the author, resolved through a `gh:` alias if one exists. It closes when the user submits a review (citing that review's chunk) or the PR is merged or closed.
- `people.link_github`: adds a `gh:<login>` alias to a dossier when the PR author's public GitHub profile name matches exactly one person's name. It runs after the cycle's dossiers are created and never guesses when the match is ambiguous. `PeopleDirectory.identifiers(id)` (emails plus `gh:` logins) is what history lookups match against.
- `projects.py`: one note per GitHub repo and per Jira project at `projects/<slug>.md`. Aliases are the repo's full and short names, or the Jira key, and the user can add more ("auth redesign"). The fence holds the 15 most recent events (commits, PRs and issues with their state, Jira issues with status), computed by code. The `handover` intent searches using these aliases.
- `ignore.py`: ignored senders. One list: `ignore` plus the older `loops.mute` in `config.yaml`, each entry an address or `@domain` (`on_list` matches exactly or by domain). `set_ignored` writes the list (un-ignoring removes the entry from both), sets or clears `ignored: true` on the sender's dossier, and dismisses their open items with reason `ignored`. `addresses_for` turns a telling into addresses, `describe` says who they are, `skipped_senders` gives the entries a question doesn't name (by address, domain or dossier name), and `ignored_person` is what the audit checks.
- `dates.py`: `due_in(text, written)` parses a due date from a verified quote (weekdays, "next Wed", today/tomorrow, month-day and ISO dates), relative to when it was written. Used by email, Jira and notes loops.
- `jira_loops.py`: a new Jira comment that @mentions the user (`mentions_me`, not written by them) goes through the same verified `loops_extract` as email, producing `asked_of_me` only, with the comment author as counterpart. The user's own later comments are checked with `loops_close`. Comments seen per issue are tracked in `state/jira_seen.yaml`.
