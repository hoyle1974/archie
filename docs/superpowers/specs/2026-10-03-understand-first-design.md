# Understand first, then act: design

**Status:** approved in conversation 2026-10-03; waiting on spec review. No code yet.
**Date:** 2026-10-03
**Builds on:** [Gemini backend with a line output format](2026-10-03-gemini-line-format-design.md)

## Goal

Make `archie ask` behave like an assistant instead of a menu. Today one model call picks
one of about 14 fixed intents from the latest message alone. Anything that isn't a
question on that menu gets misfiled. In the logged history:

- "ftbrmktf@sxziiqsov.us is spam" went to search, and search argued with the user.
- "you can ignore this sender" got the help menu.
- "show 1" got the help menu.
- Follow-up questions about the earbud thread each started over and contradicted each
  other.
- The user's answer to Archie's own "Who is …?" question was never matched to it.

The user chose six behaviors: being taught, following a conversation, being honest about
what it can't do, asking back instead of guessing, acting on instructions, and bringing
things up unprompted. This design covers all six, through new vignettes N–R.

It is approach **B** from the design conversation: understand the message first, then
send each part where it belongs. It is built so it can later grow into **C**, where the
model gets tools: the action list in §4 becomes that tool list.

## Constraints (unchanged)

- Files under `~/.archie/` are the source of truth. Everything here is stored in files:
  the conversation, the told record, the ignore list, and pending questions.
- The model's factual claims carry `[n] "quote"` citations, and the verifier drops any
  quote that isn't in its chunk. Counts and dates come from code.
- **The user's own words are never checked against the archive.** The verifier is for the
  model's claims, not for the user's.
- Connectors and Archie are read-only toward remote services. Archie never sends, posts or
  replies.
- One fast-tier model call to understand a message, as today (the router's call is
  replaced, not added to). Replies use the line format (`archie/llm/shape.py`).
- New capability = a new `ask` intent or action, not a new command.
- Answers open with a plain-English summary.

## 1. Vignettes N–R (the targets)

Added to `docs/VIGNETTES.md` with ⬜ rows in the Coverage table. Each gets an end-to-end
test in `tests/vignettes/` with the fake backend and fixture data.

- **N. Telling Archie something.** The user replies to a "Who is …?" question with
  "ftbrmktf@sxziiqsov.us is spam, ignore it."
- **O. Follow-ups.** "Did Status reply about my earbud?", then "Do you see the message I
  sent them?", "show 1" and "really?".
- **P. "I can't do that yet."** "email Workpersonthree that the pizza's picked up", "only show work
  stuff on weekdays".
- **Q. "Which one did you mean?"** "she's done with it" while two women have open items.
- **R. Nudges.** Waiting three days on HeadphonesRUs about the earbud pairing.

The full text, with what Archie shows and the pass test, is in `docs/VIGNETTES.md`.

## 2. Understanding a message

### 2.1 Order of checks

`ask()` tries these in order and stops at the first that applies:

1. **Code-only shortcuts** (no model call):
   - the existing `quick_route` patterns ("what's next?", "what do I owe people?");
   - `show N` / `open N` / `source N`: opens citation N of the last answer (§2.4);
   - a reply to a pending "which one?" question that names an option by number or by a
     word only that option contains (§5.1);
   - a plain yes or no when exactly one yes/no question is open (as today).
2. **The understanding call** (one fast-tier call), for everything else.

### 2.2 The understanding call

Replaces `route_all` in `archie/ask/router.py`. The prompt (`prompts/understand.md`)
gets:

- the message;
- up to the last 3 exchanges, if the latest was less than 30 minutes ago (§2.3); each one
  is the user's words, the rewritten question, the answer's summary text, and its
  numbered citation labels;
- Archie's open questions, numbered (all kinds, including `who_is` and nudges);
- a pending "which one?" question and its options, if any;
- today's date and weekday, and the user's name.

It returns the message split into **parts**. Each part is a record:

```
PART question
text: Do you see the message I sent them?
resolved: Do you see the message I sent HeadphonesRUs about the earbud pairing?
intent: search
people: HeadphonesRUs
topic: earbud pairing
since: -
until: -
meeting: -

PART tell
text: ftbrmktf@sxziiqsov.us is spam, ignore it.
about: ftbrmktf@sxziiqsov.us
fact: ignore

PART answer
text: it's my plumber
question: 2

PART instruct
text: snooze that till Monday
action: loop_snooze
target: HeadphonesRUs earbud pairing
until: 2026-10-05

PART unclear
text: she's done with it
options: 3; 5
ask: Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?
```

Kinds and where they go:

| Kind | Goes to |
|---|---|
| `question` | the existing intent named in `intent`, run on `resolved`, with the parameters (the router's job today) |
| `tell` | §3 |
| `instruct` | §4 |
| `answer` | the open question numbered `question`, handled like a `tell` about that question's subject (a `who_is` answer is a person fact; a yes/no answer goes to the existing `clarify` code) |
| `unclear` | §5.1 |

Rules the code enforces, whatever the model says:

- A part's `text` must appear in the message (whitespace-normalized), or the part gets the
  whole message, as `split_parts` does today.
- `resolved` is only used for questions. It must not add facts: if it names people or
  topics that appear neither in the message nor in the last exchanges given to the model,
  code uses `text` instead.
- `options` and `question` numbers must exist in the lists the model was shown.
- A reply with no parts is treated as one `question` part with intent `search`.
- The intent list no longer contains `remember` (it becomes `tell` with `fact: person`),
  `loop_update`, `correct` or `clarify` (they become actions or answers). `help` stays an
  intent and is only chosen for questions about Archie.

### 2.3 Conversation memory

Each finished exchange is appended to `~/.archie/state/conversation.jsonl`:

```json
{"ts": "...", "said": "Do you see the message I sent them?",
 "resolved": "Do you see the message I sent HeadphonesRUs about the earbud pairing?",
 "summary": "Yes. You wrote to HeadphonesRUs on Oct 2 …",
 "citations": [{"n": 1, "file": "sources/gmail/1a0e….json", "chunk": "c6",
                "label": "You → contact@headphonesrus.example, Oct 2", "quote": "End result is …"}],
 "pending": null}
```

- "Recent" means the last 3 entries, as long as the newest is under 30 minutes old (by
  `ctx.now`). After 30 quiet minutes the conversation starts fresh, so an unrelated
  question doesn't pick up an old topic.
- The file keeps the last 200 entries; older ones are dropped when it is written.
- `logs/usage.jsonl` keeps its role as the triage log. It also records each part's kind,
  any gap (§4.3) and whether a shortcut was used.

### 2.4 Follow-ups

- **"show N"** prints citation N of the last answer: its label, the quote, and the file
  path, plus a few lines around the quote from the chunk. If there's no such citation:
  "The last answer has citations 1–3."
- **"really?" / "are you sure?"** is recognized by code (no extra model call to classify
  it). The previous question is asked again in full, and the reply opens with "I checked
  again." If the sources behind the answer changed completely, or one answer found
  something and the other didn't, it adds "This is different from my earlier answer."
- Other follow-ups ("do you see the message I sent them?") work through `resolved`.

## 3. Things the user tells Archie

### 3.1 Saved first

Every `tell` part (and every `answer` part) is appended to `~/.archie/journal/told.md`
before anything is applied, as one line:

```
- 2026-10-03 · "ftbrmktf@sxziiqsov.us is spam, ignore it." → ignoring ftbrmktf@sxziiqsov.us
```

The quoted words are the part's `text`, which code has checked is in the message. The
part after the arrow is written by code from what was applied ("saved only" if nothing
was). The file is the user's to read and edit; Archie only appends.

### 3.2 Applied where it fits

`fact` is one of:

1. **`person`**: relationship, role, pronouns, identity, words to avoid, other names.
   This is today's `remember` code (`apply_facts`), moved into a `tell` applier. The
   person part carries the same fields as today's `PERSON` record. The sentence is also
   added to that person's `## My notes`, and the `who_is` question about them resolves
   as it does today.
2. **`ignore`** / **`unignore`**: §3.3.
3. **`other`**: saved only. Reply: "Saved. I don't use that for anything yet." and a gap
   is recorded (§4.3).

### 3.3 Ignoring a sender

- `about` is resolved by code to email addresses: an address or `@domain` in the text, or
  the addresses of the one person the name matches (two or more matches: ask which, §5.1).
- The addresses go into a new top-level `ignore:` list in `~/.archie/config.yaml`.
  Existing `loops.mute` entries keep working and are treated as part of the same list.
  `unignore` removes them from both.
- Ignoring writes `ignored: true` on the sender's dossier, if there is one, so the
  dossier says why it's quiet.
- Effects, all in code:
  - **Open items:** no new items from their mail (the existing `loops.mute` check, now
    reading the combined list). Existing open items from them are dismissed with the
    reason "ignored".
  - **Questions:** no `who_is`, `loop_done` or `loop_stale` questions about them; any
    open ones resolve.
  - **Today:** they don't appear.
  - **Answers:** excerpts sent by them are left out of retrieval unless the question names
    them (their name, address or domain). This needs the sender on email excerpts: the
    Gmail chunker records the message's sender address in a new `sender` field and index
    column. The index is rebuildable, so `archie admin reindex` fills it.
- Reply (written by code): "Got it. I'll ignore Goodcompany (ftbrmktf@sxziiqsov.us)
  from now on. Say 'stop ignoring Goodcompany' to undo."

### 3.4 Added while building step 2

- The told line is written after applying (so the arrow can say what happened), in a
  `finally`, so the words are saved even if applying fails.
- Yes/no answers are saved too, with the first line of Archie's reply after the arrow.
- A question about something the user sent ("the message I sent them") sets `mine: yes`;
  the search tries the user's own mail first. Found in step 1's live check.
- An answer with no claims, where none were dropped, says "I found related material, but
  none of it answers that." instead of "couldn't verify".
- When Archie knows a sender only by address, the reply names the address (vignette N).
- Answers leave out only the explicit `ignore:` entries. `loops.mute` entries are added
  automatically after two dismissals (possibly a colleague), so they keep stopping open
  items and questions but don't hide mail from answers.
- The user's own domain can't be ignored either, and when two people share a name, the
  "Which one?" question shows each one's address.

## 4. Instructions

### 4.1 Actions

Each action is a function that takes the part and returns a sentence describing what it
actually did. The list:

| Action | Code |
|---|---|
| `loop_done`, `loop_snooze`, `loop_dismiss`, `loop_reopen` | the existing `loop_update` code |
| `meeting_type`, `merge_names` | the existing `correct` code |
| `notes` | the existing `notes` intent |
| `ignore`, `unignore` | §3.3 |
| `show_citation` | §2.4 |
| `nudge_snooze` | §5.2 |

Picking which open item an instruction means stays where it is today: the action's code
lists the candidates and the fast model picks numbers (one call, only when needed).

### 4.2 Confirmations come from code

The reply to an instruction is built only from the sentences the actions returned
("Snoozed until Monday: HeadphonesRUs, earbud pairing."). The model never writes "done" or
"sent". If an action failed or matched nothing, the reply says that.

### 4.3 What Archie can't do

- **Sending or posting** (email, messages, invites, comments, replies): `action: send` →
  "I can't send anything; I only read." This is permanent, not "yet".
- **Any other instruction** that maps to no action: `action: none`, with a `wanted` field
  holding a short verb phrase for the request ("filter Today by day"). Reply: "I can't
  filter Today by day yet." The phrase describes the request, not the archive, so it
  needs no citation. If `wanted` is missing or longer than 12 words, the reply quotes the
  part's text instead: "I can't do “only show work stuff on weekdays” yet."
- In both cases any `tell` parts of the same message are still saved and applied, and the
  reply says so first ("I saved that the pizza's picked up.").
- The instruction is recorded as a gap: `"gap": "<the part's text>"` in
  `logs/usage.jsonl`. An `action: none` request is also appended to `journal/told.md`
  (`→ can't do this yet`), and the reply adds "I've saved that you want it." A `send`
  request is not saved as a wish.
- The help menu is never the reply to a `tell` or `instruct` part.

## 5. Asking back, and nudges

### 5.1 "Which one did you mean?"

- When more than one thing fits, the understanding call returns an `unclear` part with
  the option numbers and a short question. An action's own candidate pick can also return
  more than one item for a singular reference; that becomes an `unclear` part too.
- Code checks the options exist and writes the question from them (the model's `ask` text
  is used only if every option it names is one of the listed options; otherwise code
  writes "Which one: A or B?").
- The pending question is saved in the conversation entry (`pending`): the options, the
  original part and its kind.
- The next message, within the 30-minute window, is first matched against the options by
  code (a number, "the first/second one", or a word unique to one option). Otherwise the
  understanding call sees the pending question and returns an `answer` part for it. The
  original part then runs on the chosen item.
- After 30 minutes the pending question is dropped and nothing happens.

### 5.2 Nudges

- A new audit question kind, `waiting_nudge`, built by code in `archie/derive/audit.py`
  from open `waiting_on` items:
  - the item is open (not snoozed, done or dismissed);
  - it is at least `nudges.after_days` (default 3) days old, counted from `created_at`;
  - no message from the counterpart is in the thread after `created_at`.
- Text: "Still waiting on HeadphonesRUs about the earbud pairing (3 days). Want to follow
  up?"
- Priority order: `same_person`, `loop_done`, `loop_stale`, `waiting_nudge`, `who_is`.
  The limit of 5 open questions (`MAX_OPEN`) still applies.
- Replies go through the understanding call as `answer` parts:

| User says | Result |
|---|---|
| "I'll give them till Monday" | the item is snoozed until Monday |
| "they replied" / "done" | the item is marked done |
| "drop it" | the item is dismissed |
| "yes, I'll follow up" | the item is snoozed for `nudges.after_days` days (Archie never sends anything) |

- It resolves on its own when the counterpart replies or the item closes. It comes back
  only if a snooze ends and there's still no reply.

## 6. Build order

Five steps. Each ends with its vignette test passing and vignette tests A–M still passing.

1. **Understanding and follow-ups (O):** `conversation.jsonl`, the understanding call
   replacing `route_all`, the shortcuts, "show N", "really?". Existing intents keep
   working through `question` parts; `remember`, `loop_update`, `correct` and `clarify`
   keep working through temporary mappings until steps 2–3 replace them.
2. **Telling (N):** `journal/told.md`, the `person` applier, ignore/unignore with all four
   effects, the `sender` index field.
3. **Instructions (P):** the action list, code-written confirmations, the no to sending,
   gaps.
4. **Which one (Q):** pending questions and matching the reply.
5. **Nudges (R):** `waiting_nudge` and its replies.

## 7. Testing

- **Vignettes:** `tests/vignettes/test_n_*.py` … `test_r_*.py`, end to end with the fake
  backend and fixture data, checking what the user sees and what was written to files.
- **Unit tests:**
  - parsing the `PART` records and the code-enforced rules in §2.2;
  - the 30-minute window and the 200-entry cap;
  - "show N" with and without a matching citation;
  - each ignore effect, and undo;
  - matching a reply to a pending question by number, ordinal and unique word;
  - nudge timing, priority, and each reply.
- **Live checks** with Gemini after steps 1 and 5: a few real messages, including the
  logged ones that failed, with the cost measured. Expected: about 0.1¢ more per message,
  since the understanding call also reads the recent exchanges.

## 8. Docs

- `docs/VIGNETTES.md`: N–R added now; Coverage rows updated as each test passes.
- `docs/DESIGN.md` §8 (`archie ask`): the understanding step, parts, conversation memory,
  told record, actions, and the intents table without `remember`, `loop_update`,
  `correct` and `clarify`. §4 (storage layout): `state/conversation.jsonl`,
  `journal/told.md`, the `ignore:` list. §5.4: the `sender` column.
- OKF bundle: the ask pipeline and router components, questions (audit), loops, and
  `okf/log.md`.

## Out of scope

- Model tools (approach C).
- Any sending, drafting or replying.
- Applying `other` tellings anywhere (they're saved and counted as gaps; the most common
  ones decide what to build next).
- Fixing the dossier facts that ignore what the user said about *other* people (the
  "son" wording in Goodspouse's notes). That's a separate fix in `derive/enrich.py`.
