# Archie — Vignettes (the targets)

These are the situations Archie exists for. **Every feature must trace to at least one
vignette, and every vignette must eventually pass its end-to-end test**
(`tests/vignettes/test_<letter>_*.py`). Design details live in [DESIGN.md](DESIGN.md).

When building, check: *which vignette does this move forward?* If none, stop and ask.

## Coverage

Status: ⬜ not started · 🟨 partial · ✅ test passing

Tests check what the user sees, not only what the model was shown. A part of a vignette
that isn't built yet has a test marked `xfail(strict=True)` naming the gap, and its row is
🟨. Once that part is built, the test passes and strict mode makes pytest report it. Then
remove the mark and set the row to ✅.

| # | Vignette                     | Needs (sources → capabilities)                                  | Milestone | Status |
|---|------------------------------|-----------------------------------------------------------------|-----------|--------|
| A | Pre-meeting briefing         | Calendar, Gmail, Drive → meetings, people, loops, brief         | M2 (standard, 1:1), M3 (standup), M4 (all-hands) | 🟨 no "refreshed" time |
| B | Who is this? (memory assist) | Calendar, Gmail → people, entity resolution                     | M2 | 🟨 "Priya S." not found; no role from signatures |
| C | The open loop I forgot       | Gmail (+Jira, GitHub) → loops detect/close                      | M2 (email), M3 (Jira/GitHub) | 🟨 email+Jira not merged |
| D | What should I work on next?  | loops + calendar + Jira/GitHub → ranking                        | M3 | ✅ |
| E | Performance review ledger    | GitHub, Jira, Drive, meetings → ledger                          | M3 | ✅ |
| F | Incident: who touched it?    | GitHub, Jira → hybrid search                                    | M3 | ✅ |
| G | Project handover             | all → projects, handover                                        | M4 | ✅ |
| H | After the meeting            | meetings → notes intake, action items → loops                   | M2 | ✅ |
| I | Back from time off           | all → catch-up                                                  | M4 | ✅ |
| J | Before I reply               | Gmail → who/history                                             | M2 | 🟨 open items not shown |
| K | Weekly brag doc              | ledger → journal                                                | M4 | ✅ |
| L | Someone new                  | Calendar, Gmail → stub dossiers, bootstrap                      | M2 | ✅ |
| M | Conflicting sources          | all → conflict callout in briefings                             | M3 | ✅ (both sides reach the model) |
| N | Telling Archie something     | Gmail, questions → understand, told record, ignore list         | M5 | ✅ |
| O | Follow-ups                   | ask history → understand, conversation memory, citations        | M5 | ✅ |
| P | "I can't do that yet"        | ask → understand, actions, gaps                                 | M5 | ✅ |
| Q | "Which one did you mean?"    | loops, people → understand, pending questions                   | M5 | ✅ |
| R | Nudges                       | Gmail, loops → audit (waiting_nudge), snooze                    | M5 | ✅ |
| U | News that finishes an item   | loops → understand (open items), loop_done, told record         | M5 | ✅ |

### Milestones

- ✅ **M1 Foundation** (done 2026-10-01): `~/.archie` layout, `me.yaml`, store with fences, chunker, index
  (FTS5 + vec), hybrid search, LLM interface and verifier, `ask` router skeleton plus
  `search` and `help`, TUI shell with catch-up sync. *Exit:* the rebuild, fence and
  verifier tests pass.
- ✅ **M2 Know my day** (done 2026-10-02; tests in `tests/vignettes/test_m2.py`. Calendar and Drive have only been tested against fakes so far and need `archie admin connect google` before a live run): Calendar, Gmail and Drive connectors. Meetings, people and email
  loops. Standard and 1:1 briefings with T-15 notify. Notes intake. *Exit:* A (standard,
  1:1), B, C (email), H, J and L pass.
- ✅ **M3 Know my work** (done 2026-10-02; tests in `tests/vignettes/test_m3.py`. Live GitHub is verified; Jira has only been tested against fakes so far): GitHub and Jira connectors. Standup briefing, `next`, ledger,
  conflicts, closing loops across channels. *Exit:* A (standup), C, D, E, F and M pass.
- ✅ **M4 Long arc** (done 2026-10-02; tests in `tests/vignettes/test_m4.py`): projects, handover, catch-up, weekly journal, all-hands. *Exit:* all pass. (2026-10-03: stricter on-screen tests reopened gaps in A, B, C and J; see the Coverage table.)
- **M5 Understand first** ([spec](superpowers/specs/2026-10-03-understand-first-design.md)): understand each message before acting, conversation memory, the told record, ignoring senders, actions with honest "can't yet" replies, asking which one, nudges. *Exit:* N, O, P, Q and R pass.
- **Phase 2:** the Slack connector. Then re-run every vignette with Slack data in the fixtures.

---

## A. Pre-meeting briefing

**Situation.** 1:45 PM. A 2:00 "Design Review: Auth Redesign" with Alex Rivera and Priya
Sharma. Alex edited the linked doc 30 minutes ago and merged a related PR yesterday. The
user promised Alex a review that's due today.

**What happens.** The briefing was built at 8:02 in the morning batch. At 1:45 the
packet hash changed (the doc edit), so it rebuilds and a macOS notification fires. The
feed pane shows it.

**Archie shows:**
```
2:00 PM · Design Review: Auth Redesign · 45 min

Alex and Priya want sign-off on moving session tokens to Redis. You owe Alex
a review of the fallback logic (due today), and Alex merged a related pool fix
yesterday.

People
  Alex Rivera — Senior Backend Eng. Last talked Oct 14 (1:1). Prefers code over prose.
  Priya Sharma — PM, auth. Last talked Sep 30 (planning).

Open with these people
  • You → Alex: review Redis fallback logic (due today) [1]

What changed
  • Auth_Migration_Draft edited by Alex 30m ago: adds Redis cluster section [2]
  • PR #412 "Fix redis connection pool drop" merged yesterday [3]
```

**By meeting type:**
- **1:1 (recurring, 2 people):** opens with "Since your last 1:1 (Oct 7)". It covers
  their commitments and their status, what they shipped, the user's commitments, and
  topics the user saved for them ("feedback: great incident write-up").
- **Standup:** *Yesterday:* PRs and commits and Jira transitions, computed by code.
  *Today:* In Progress issues plus anything due. *Blockers:* urgent `asked_of_me` loops
  from the last 12h.
- **All-hands (25+ people):** leaders attending (role only) and recent org-wide docs and
  announcements. No peer detail and no individual tickets.
- **Standard:** everything above for each attendee, plus linked doc status.

**Acceptance:** each fact traces to fixture data. The meeting type comes from the
resolution rules. A fixture edit after the morning batch triggers exactly one rebuild.

## B. Who is this? (memory assist)

**Situation.** A call starts with someone the user last spoke with months ago, and the
name isn't coming back.

**User:** `ask "who is Priya?"` (or the briefing already shows it).

**Archie shows:**
```
Priya Sharma is the PM for auth. You last talked Sep 30 in quarterly planning,
where she pushed to ship SSO before the Redis migration [1].

  Role: Product Manager (auth) · Internal
  Worked together on: auth-redesign, SSO rollout
  Last 3 interactions: Sep 30 planning · Sep 22 email re: SSO dates · Sep 9 design review
  Your notes: "Likes data. Bring the latency graph."
```

**Acceptance:** "Priya", "priya.s@company.com" and "Priya S." all resolve to one
dossier. Ambiguous names ("Alex" with two Alexes) get a question back, not a guess.
"What's Priya's role?" (also "Priyas", without the apostrophe) answers from the archive.
A title in someone's email signature becomes their role, cited and dated, even when it's
in an older email behind newer threads they were only copied on. If their emails give two
different titles, both are shown with dates, as in M.

## C. The open loop I forgot

**Situation.** Three days ago Sarah emailed "can you review the Redis fallback patch
before Friday?" The user never replied.

**What happens.** On the morning batch the loop (opened at ingest) is now aging and due
tomorrow, so it ranks first in the feed. `ask "what do I owe people?"` lists it.

**Archie shows:**
```
You have 3 open items. The most urgent: Sarah asked for a review of the
Redis fallback patch, due tomorrow, and you haven't replied [1].

  1. Sarah Jones — review Redis fallback patch · due Fri · 3 days old [1]
  2. Ken Ito — send the Q4 capacity numbers you promised · 5 days old [2]
  3. (waiting on) Priya — SSO launch date · asked 4 days ago [3]
```

**Closure:** the user submits a PR review on the patch, a cross-channel match is
verified, and the loop moves to `done` with `closed_by` citing the review. Or the user
says `ask "done with Sarah's review"`. Or `ask "that's not a loop"` dismisses it and
records a reason.

**Acceptance:** newsletters and automated mail never create loops. A loop never closes
without cited evidence or the user's word. Dedup: the same ask in email and Jira makes
one loop with two sources.

## D. What should I work on next?

**User:** `ask "what should I do next?"` at 9:10 AM.

**Archie shows:**
```
You have 50 minutes before standup. Best use: answer Sarah's review request
(due tomorrow, blocks Alex), then finish ENG-402, which is In Progress and
you'll report on at standup.

  1. Review Redis fallback patch for Sarah — due tomorrow, blocks Alex's PR [1]
  2. ENG-402 token expiry — In Progress 3 days; standup at 10:00 [2]
  3. Send Ken the Q4 capacity numbers — promised 5 days ago [3]
  Why this order: due soonest · blocks someone · then oldest promise
```

**Acceptance:** the ranking comes from code (§6.5) and each item explains why. Calendar
gaps are computed, not guessed.

## E. Performance review ledger

**Situation.** A year in, review season. **User:** `ask "what did I accomplish since
last October?"`

**Archie shows:** a summary paragraph, then per-quarter sections, each grouped by
project: merged PRs, closed issues, docs written or substantially edited, incidents
handled, people helped (reviews given, questions answered). Every line is cited. Counts
are computed by code.

**Acceptance:** nothing outside the requested window appears, and nothing is invented.
Counts match the fixtures exactly. It works over arbitrary windows ("Q3", "last 6 months").

## F. Incident: who touched it?

**Situation.** Auth errors spike. **User:** `ask "who changed the auth service config
last week?"`

**Archie shows:**
```
Two changes to auth config last week: Alex raised the Redis pool size in
PR #412 (Tue), and Dana changed token TTL in commit 9f3c1e2 (Thu) [1][2].
```
with the files touched, the authors and links.

**Acceptance:** exact identifiers (file paths, ticket keys, error strings) are found by
FTS. Conceptual phrasing ("the thing that changed session timeouts") is found by vector
search.

## G. Project handover

**User:** `ask "write a handover for auth-redesign"`

**Archie produces** a Markdown document: purpose, current state, key decisions (with
dates and who decided), linked docs, open issues and loops, people and their roles,
known risks and tech debt. It is saved to `projects/auth-redesign-handover-<date>.md`.

**Acceptance:** every decision cites its source, and open loops for the project are all
included.

## H. After the meeting

**Situation.** The design review just ended. The user pastes rough notes.

**User:** `ask "notes from the design review: Redis approved, Alex to add circuit
breaker, I need to update the runbook by next Wed"`

**What happens.** Archie matches "design review" to the meeting that just ended (and
asks if it's ambiguous). It writes the notes under `## My notes`. It extracts action
items and creates an `i_promised` loop (update runbook, due next Wed) and a `waiting_on`
loop (Alex: circuit breaker).

**Also:** the user's private Google Doc of notes for the meeting is picked up by the
notes connector (design deferred). The TUI may prompt "Any notes from Design Review?"
at the end of a meeting.

**Acceptance:** the notes are stored verbatim. The action items are verified against the
note text, and "next Wed" resolves to a concrete date.

## I. Back from time off

**User:** `ask "what happened while I was out last week?"`

**Archie shows:** a summary, then what changed in the user's projects, decisions made
without them, loops that opened while they were away (sorted by urgency), and meetings
they missed, with notes if any exist.

**Acceptance:** limited to the window and to things involving the user's people and
projects, so it isn't a firehose.

## J. Before I reply

**Situation.** The user is about to answer an email from Ken and can't remember the
context.

**User:** `ask "what's my history with Ken?"` or `ask "what's going on with Ken's capacity email?"`

**Archie shows:** who Ken is, the last few exchanges, open loops in both directions
("you promised him Q4 numbers 5 days ago"), and the thread's state.

## K. Weekly brag doc

**What happens.** Friday afternoon (the first cycle after 3 PM), Archie writes
`journal/weekly/2026-W40.md`: shipped, unblocked others, decisions, and docs. The
quarterly ledger (E) is built on top of these.

**User:** `ask "what did I get done this week?"` shows it. The user can add text
outside the fence.

## L. Someone new

**Situation.** Tomorrow's invite includes Dana Kim (dana@acme.com), whom Archie has
never seen.

**What happens.** Ingest creates a `status: stub`, `org: external` dossier. Bootstrap
searches all mail and docs for "dana@acme.com" and "Dana Kim" and fills the fenced
section with cited mentions. The briefing says: "New: Dana Kim (external, acme.com).
Mentioned in 2 threads: …"

**Acceptance:** no fabricated role or background. If there are zero mentions, it says so.

## M. Conflicting sources

**Situation.** An email from Priya says "auth migration is paused pending security
review", while GitHub shows Alex pushed 3 commits to `auth-v2` yesterday.

**Archie shows** (inside any relevant briefing or answer):
```
⚠️ Conflict: Priya's email (Oct 12) says the migration is paused [3], but Alex
pushed 3 commits to auth-v2 yesterday [4]. Worth asking which is current.
```

**Acceptance:** both sides are cited and verified. Archie never decides which side is
true.

## N. Telling Archie something

**Situation.** Today shows "Who is ftbrmktf@sxziiqsov.us?" It's a Goodcompany
marketing sender.

**User:** `ask "ftbrmktf@sxziiqsov.us is spam, ignore it"`

**Archie shows:**
```
Got it. I'll ignore ftbrmktf@sxziiqsov.us from now on.
Say "stop ignoring ftbrmktf@sxziiqsov.us" to undo.
I also dismissed 1 open item from them.
```

Archie only knows this sender by address (that's why it asked), so the reply names the
address. When a sender has a name, the reply uses it: `Goodcompany
(ftbrmktf@sxziiqsov.us)`. The last line appears only when open items were dismissed.

**What happens.** The sentence is saved word for word in `journal/told.md`. The address
goes into the `ignore:` list in `config.yaml`, and the "Who is …?" question resolves.
From then on the sender creates no open items or questions, doesn't appear in Today, and
isn't cited in answers unless the user asks about them by name.

**Acceptance:** the user's words are in the file. The next sync's checks ask nothing about
the sender, answers don't cite them, and "stop ignoring ftbrmktf@sxziiqsov.us" undoes it. The
user's statement is never checked against the archive.

**Telling Archie about a person.** `ask "Acorn's full name is Acorn Testerson. Acorn
is full of energy and is 3 and a half years old."` gets:
```
Got it. I'll remember:
  • Acorn (Acorn Testerson), new
```
Any sentence about a person (their age, what they're like) is saved word for word in that
person's "My notes", never "Saved. I don't use that for anything yet." A full name the
user gives is kept beside the name they use: answers say "Acorn", with the full name in
brackets where it helps ("Acorn (Acorn Testerson)").

## O. Follow-ups

**Situation.** The user asks `ask "did Status reply about my earbud?"` and gets an answer
with citations [1]–[3].

**User:** `ask "do you see the message I sent them?"`, then `ask "show 1"`, then
`ask "really?"`

**Archie shows:** an answer about the user's own message to HeadphonesRUs about the earbud
pairing. Then citation [1] of that answer: its source, the quote and the file. Then the
question checked again, opening with "I checked again", and saying so if the answer
changed.

**Acceptance:** "them" and the topic are worked out from the last few exchanges.
Citations from the previous answer can be opened. After 30 quiet minutes, or for an
unrelated question, the old topic isn't pulled in.

## P. "I can't do that yet"

**User:** `ask "email Workpersonthree that the pizza's picked up"` or
`ask "only show work stuff on weekdays"`

**Archie shows:**
```
I saved that the pizza's picked up. I can't send anything; I only read.
```
or
```
I can't filter Today by day yet. I've saved that you want it.
```

**Acceptance:** something the user told Archie never gets the help menu. Archie never
claims it did something it didn't do: confirmations are written by code from what
actually ran. The request is recorded as a gap in the usage log.

## Q. "Which one did you mean?"

**Situation.** Workpersonthree (pizza instructions) and Workpersonfour (an IEP form) both have open items
with the user.

**User:** `ask "she's done with it"`

**Archie shows:**
```
Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?
```

**User:** `ask "Workpersonthree's"`

**Archie shows:** `Marked done: Workpersonthree, pizza instructions.`

**Acceptance:** whenever more than one thing fits, Archie asks instead of guessing. The
short reply is applied to the right item. If the user doesn't answer within 30 minutes,
nothing happens.

## R. Nudges

**Situation.** Three days ago the user asked HeadphonesRUs about the earbud pairing. There's
no reply.

**Today shows:**
```
Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow up?
```

**User:** `ask "I'll give them till Monday"`

**Archie shows:** `Snoozed until Monday: HeadphonesRUs, earbud pairing.`

**Acceptance:** nudges come from code (the item's age, and no reply in the thread). They
count toward the limit of five open questions and go quiet once the user answers. A reply
from HeadphonesRUs clears the nudge. "Yes, I'll follow up" waits another three days;
Archie never sends anything.

## U. News that finishes an open item

**Situation.** Archie has an open item "Troubleshoot new earbud pairing issue", waiting on
HeadphonesRUs. The user got the earbuds working themselves and hasn't emailed yet.

**User:** `ask "I was able to get my status earbuds to pair. I will let them know it works now."`

**Archie shows:** `Marked done: HeadphonesRUs, troubleshoot new earbud pairing issue.`

If more than one item could match, Archie asks which one (vignette Q). News that matches no
open item is saved as before.

**Acceptance:** the item moves to `done` on the user's word, the sentence is in
`journal/told.md` with what Archie did, and no gap is logged. "I will let them know" is the
user's own plan, not a request to send anything (Archie never sends).
