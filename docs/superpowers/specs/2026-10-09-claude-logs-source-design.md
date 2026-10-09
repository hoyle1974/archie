# Claude Code sessions as an Archie source: design

**Status:** approved in conversation 2026-10-09; spec awaiting review. No code yet.
**Date:** 2026-10-09

## Goal

Make the user's Claude Code sessions part of Archie's memory:

1. **Search and cite.** `ask "when did we decide to drop web search?"` finds the exchange
   and cites it, through the existing search path (no new command, no new intent).
2. **Record.** Sessions count as work in the standup, catch-up (I), the weekly brag doc
   (K) and the review ledger (E).

## Why a slim copy, not a symlink

The first idea was to symlink `~/.claude/projects` and index in place. Measured on
2026-10-09:

- **Claude Code deletes its logs after 30 days** (`cleanupPeriodDays`, default 30, not
  overridden). The oldest log on disk was from 2026-09-08, exactly 31 days earlier. A
  link would dangle a month later, breaking DESIGN §2.1 (files are the source of truth)
  and §2.9 (keep everything).
- **The logs are mostly not conversation.** Tool output, attachments and file snapshots
  dominate. Keeping only prompts, text replies and session metadata:

  | | Files | Raw | Slim |
  |---|---|---|---|
  | Main sessions | 92 | 188 MB | 3.2 MB |
  | Subagent logs | 170 | 78 MB | 1.2 MB |

  That is 1.7% of raw, about 40 MB a year without subagents.

So the connector writes a slim copy under `sources/claude/` and records where the full log
was. Within 30 days the full transcript is still reachable through that path.

## Raw file

One file per session: `sources/claude/<project>/<session_id>.json`.

```json
{
  "session_id": "df9db305-31af-431a-82c6-b6d279545b2e",
  "title": "Claude log retention period",
  "project": "archie",
  "cwd": "/Users/ttesterson/code/archie",
  "branch": "main",
  "started_at": "2026-10-09T16:02:11Z",
  "ended_at": "2026-10-09T17:40:55Z",
  "original": "~/.claude/projects/-Users-ttesterson-code-archie/df9db305-31af-431a-82c6-b6d279545b2e.jsonl",
  "turns": [
    {"role": "user", "at": "2026-10-09T16:02:11Z", "text": "okay, now I want to add claude logs…"},
    {"role": "assistant", "at": "2026-10-09T16:03:40Z", "text": "Before going further, here's something…"}
  ]
}
```

- `title`: the last `ai-title` record's `aiTitle`; `null` if the session has none.
- `project`: the basename of the first record's `cwd`. `branch`: its `gitBranch`.
- `started_at` / `ended_at`: the first and last kept turn's `timestamp`, UTC.
- `original`: the source path, written with `~` for the home directory.

### What is kept

Records of `type` `user` or `assistant`, not `isMeta`, not `isSidechain`, not
`isCompactSummary`:

- **User:** string content, or `text` blocks of list content (never `tool_result`
  blocks). A slash command (`<command-name>/x</command-name>` …
  `<command-args>y</command-args>`) is kept as `/x y`.
- **Assistant:** `text` blocks only (no `tool_use`, no `thinking`).

### What is dropped

- Every other record type (attachments, file-history snapshots, mode, last-prompt, system).
- User text that is only a harness wrapper: `<task-notification>`, `<local-command-stdout>`,
  `<local-command-caveat>`, `<command-message>` without a `<command-name>`, and
  `[Request interrupted by user…]`.
- `<system-reminder>…</system-reminder>` spans inside kept text.
- **Compaction summaries** (`isCompactSummary`): a model's retelling of earlier turns must
  not be cited as what was said.
- **Subagent logs** (any path containing a `subagents` directory).
- Turns whose text is empty after the above. A session with no kept turns writes no file.

### Secret masking

`~/.archie` must stay safe to commit (DESIGN §4), and prompts sometimes contain a pasted
token. Before writing, each turn's text has matches of these replaced with
`[secret removed]`:

- `sk-[A-Za-z0-9_-]{20,}` (Anthropic/OpenAI), `gh[pousr]_[A-Za-z0-9]{30,}` (GitHub),
  `AIza[0-9A-Za-z_-]{35}` (Google), `xox[abprs]-[A-Za-z0-9-]{10,}` (Slack),
  `-----BEGIN [A-Z ]*PRIVATE KEY-----` … `-----END [A-Z ]*PRIVATE KEY-----`.

The list lives in one module-level tuple so adding a pattern is a one-line change.

## Sync

`archie/connectors/claude.py`, `ClaudeConnector`, `name = "claude"`. It reads only local
files and writes only `sources/claude/`.

- **Config:** `connectors: claude: {enabled: true, path: ~/.claude/projects}`. `path` is
  optional and defaults to `~/.claude/projects`.
- **Cursor:** the UTC time of the last sync. A run converts every main-session
  `*.jsonl` whose mtime is at or after `cursor - 1 hour` and writes it with `write_raw`
  (atomic). A session still in progress is simply rewritten each cycle.
- **First sync takes every log on disk**, ignoring `backfill_days`. This is a deliberate
  exception to DESIGN §5.1: the source is local, and anything older than 14 days would be
  deleted by Claude Code within days, so it is now or never.
- **Originals deleted by Claude Code are not tombstones.** The slim copy stays, indexed.
  This is the second exception to DESIGN §4 "Deletions": the original vanishing is
  Claude Code's cleanup, not the user deleting anything.
- **Cadence:** the normal cycle (15 minutes, plus catch-up on TUI launch). No file watcher.
- **Errors:** an unreadable or partly written line is skipped; the rest of the session is
  still converted. A missing `path` raises a plain error ("Claude Code's log folder
  ~/.claude/projects isn't there"), isolated like any connector failure.

## Index

A raw chunker registered for `claude` (`register_raw_chunker`):

- **One chunk per exchange:** a user turn plus the assistant turns up to the next user
  turn, rendered as `You: …` / `Claude: …`. Exchanges over 280 words split with
  `chunk_windows` (40-word overlap). Assistant turns before the first user turn join the
  first exchange.
- `ts`: the user turn's time. `people`: empty. `source`: `claude`.
- `label`: `Claude session: <title> (<project>, <Mon D>)`, or
  `Claude session in <project> (<Mon D>)` without a title.
- Bump `CHUNKER_VERSION` so existing indexes rebuild.

## Activity

`archie/activity.py` gains kind `claude_session` ("Claude sessions"). A session is an item
in a window when at least one user turn falls inside it. The item's `title` is the
session title (or "Claude session"), `project` is the session's project, and the
citation is the first in-window exchange's chunk and its first line as the quote. This
feeds standup, catch-up, the weekly journal and the ledger with no further change.

## `show N`

A cited Claude chunk shows the exchange text and the session title, project and date.
Below it: "Full log: ~/.claude/projects/…" while the original exists, else "The full log
was removed by Claude Code's 30-day cleanup; this is Archie's copy."

## Vignette

Add **Y. What did Claude and I decide?** to `docs/VIGNETTES.md`:
`ask "when did we talk about Claude log retention?"` answers with a short summary citing
the exchange, labelled with the session title, project and date. Coverage row:
`Claude Code logs → connector, chunker, activity`.

## Testing

`tests/vignettes/test_y_claude_sessions.py`, with fixture JSONL under
`tests/fixtures/claude/`, covering:

1. The slim file has the fields above; wrappers, tool output, attachments, compaction
   summaries, `isMeta` records and subagent logs are absent; a slash command reads `/x y`.
2. Each secret pattern is masked.
3. A second sync after appending to one log rewrites only that session.
4. Deleting the original keeps the slim file and its chunks.
5. `ask "when did we talk about log retention?"` (fake LLM) cites the right exchange
   with the expected label.
6. Weekly activity lists the session under "Claude sessions".
7. `show N` says the full log is gone after the original is deleted.

## Docs and OKF

- DESIGN §4 layout gains `sources/claude/<project>/<session_id>.json`; §5.1 gains a Claude
  row (cursor: file mtime since last sync; unit: session) and the two exceptions above;
  §5.3 gains the exchange chunk unit.
- New OKF component for the connector (`status: active` once code lands), and an
  `okf/log.md` entry.

## Out of scope

- Subagent logs (can be added later behind a config flag).
- Tool calls and output, including which files a session touched.
- Deriving loops or people from sessions.
- Claude Desktop or claude.ai conversations.
