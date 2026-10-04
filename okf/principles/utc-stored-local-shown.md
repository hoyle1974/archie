---
type: Principle
title: Store UTC, show local time
description: Every stored time is ISO 8601 in UTC; only what the user reads is converted to the local timezone.
tags: [principle]
---

Stored times compare correctly as text and as datetimes only when they share one zone. Calendar events used to keep Google's local offset (`-07:00`), so `max(last_interaction)` across email and meetings could pick the wrong one. All-day dates stay plain dates.

Display goes through `archie/store/times.py`: `when()` shows "Fri Oct 2, 1:26 PM" (the year only when it isn't this year), and `stamp()` opens every answer with when Archie gave it ("Sun, Oct 4 · 9:34 AM"). Markdown written for the user to read (a loop's history, `journal/told.md`) uses local time. See [store](../components/store.md).

Source: [DESIGN §2](../../docs/DESIGN.md#2-principles-non-negotiable)
