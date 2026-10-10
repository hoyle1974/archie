---
type: Component
title: Activity
description: What the user did in a time window, computed from raw files with no LLM. Each item points at its exact source chunk.
resource: archie/activity.py
status: active
tags: [component]
---

`my_activity(ctx, start, end) -> [Item(when, kind, title, project, path, chunk, quote)]`, sorted by time.

| Kind | Where it comes from |
|---|---|
| `commit` | the user's commits on GitHub |
| `pr_merged` / `pr_opened` | PRs the user authored |
| `review_given` | the user's reviews, cited to the review's chunk |
| `issue_done` / `transition` | Jira status changes made by the user (`by_me`) |
| `doc_edited` | Drive docs whose last modifier is the user |
| `email_sent` | emails the user sent |
| `meeting` | past meetings with other attendees |
| `claude_session` | a Claude Code session with a prompt in the window |

Used by the `ledger` intent, the weekly journal, and the standup's Yesterday section (see [briefings](briefings.md)). Catch-up (Vignette I) will use it too.
