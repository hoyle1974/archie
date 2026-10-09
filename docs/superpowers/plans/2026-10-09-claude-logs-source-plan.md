# Claude Code sessions as an Archie source: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a connector that turns the user's Claude Code session logs
(`~/.claude/projects/**/*.jsonl`) into a searchable, citable Archie source, so `ask` can
answer "when did we talk about X?" and Claude sessions show up in the standup, catch-up,
the weekly journal and the review ledger.

**Architecture:** A new connector (`archie/connectors/claude.py`) follows the existing
`Connector` protocol (`async sync(sctx, cursor) -> SyncResult`). It reads local `.jsonl`
logs only (no network), writes a slim JSON copy per session to `sources/claude/<project>/
<session_id>.json` (prompts, assistant text replies, and session metadata — no tool
calls, attachments, snapshots, subagent logs, or compaction summaries), and registers a
raw chunker that turns each session into one chunk per exchange. `activity.py` gains a
`claude_session` kind, and `ask/followup.py`'s `show` command grows one line pointing at
the original log (or saying it's gone).

**Tech Stack:** Python 3.11+, stdlib `json`/`re`/`pathlib`, the existing
`archie.store.files` atomic-write helpers, `archie.index.chunk` chunking helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-claude-logs-source-design.md`

## Global Constraints

- Connectors write only under `sources/<name>/` and never send or post anything (DESIGN §2, §2.8).
- Secrets never land in `~/.archie/` (DESIGN §4): every kept turn's text is run through `mask_secrets` before it's written.
- Raw writes are atomic (`write_raw` → `atomic_write`, temp file + rename).
- Times stored in UTC ISO-8601 (DESIGN §2.10); only rendering converts to local time (`short_date`, `when`).
- `chunk_id` must be a pure function of the file's content, so the disposable index can always be rebuilt (DESIGN §5.3 note in `archie/index/chunk.py`).
- The first sync takes every log on disk, not the usual 14-day backfill (spec: "Why a slim copy" exception), because older logs are deleted by Claude Code within days.
- A session whose original `.jsonl` is later deleted by Claude Code's own cleanup is **not** tombstoned; the slim copy and its index entries stay (spec's second exception to DESIGN §4).
- A new capability is a new `ask` intent only if needed — here none is: the existing `search` intent and hybrid search already answer from any indexed source, so no new intent is added.

## Review Focus

- **A session with no kept turns** (every record filtered out: all `isMeta`, all tool calls, a session that's 100% subagent/compaction) writes no file at all — covered by `parse_session` returning `None` and the connector skipping it (Task 1, Task 2).
- **A pasted secret in a prompt** must never reach disk unmasked, including one that spans most of a line or sits next to other text — covered by `mask_secrets` tests for each pattern (Task 1).
- **A session still being written to** (the connector runs mid-conversation) must not crash on a trailing partial JSON line — covered by `parse_session` skipping an unparseable line and keeping the rest (Task 1).
- **Two sessions with the same title** (or no title at all) must still get distinct, correct chunk labels and distinct raw-file paths, since `title` is not unique — covered by labels keyed on `project`+`date`, not `title` alone, and paths keyed on `session_id` (Task 3).
- **`show N` on a Claude citation** after the connector is disabled or the config path changes must not crash looking up `c["file"]` — covered by guarding on the `sources/claude/` prefix before reading anything further (Task 5).

---

## File Structure

- **Create** `archie/connectors/claude.py` — the connector, `parse_session`, `mask_secrets`, and the raw chunker `chunk_session`.
- **Modify** `archie/connectors/registry.py` — register `ClaudeConnector` under `"claude"`.
- **Modify** `archie/index/chunk.py` — bump `CHUNKER_VERSION` (an existing chunker's output format didn't change, but adding a new one that could be mis-cached on a dev checkout that already indexed raw `claude` paths under an old dev build is cheap insurance; see Task 3).
- **Modify** `archie/activity.py` — add the `claude_session` kind.
- **Modify** `archie/ask/followup.py` — `show()` adds the "full log" / "removed by cleanup" line for a Claude citation.
- **Create** `tests/unit/test_claude.py` — pure-function tests (masking, parsing, chunking) with no network or real `~/.claude`.
- **Create** `tests/vignettes/test_y_claude_sessions.py` — the end-to-end vignette test.
- **Modify** `docs/DESIGN.md`, `docs/VIGNETTES.md`, `okf/components/connectors.md`, `okf/components/activity.md`, `okf/log.md` — narrative updates (Task 7).

---

### Task 1: Parsing and secret masking (pure functions)

**Files:**
- Create: `archie/connectors/claude.py`
- Test: `tests/unit/test_claude.py`

**Interfaces:**
- Produces: `mask_secrets(text: str) -> str`, `parse_session(path: Path) -> dict | None`,
  constant `NAME = "claude"`, constant `DEFAULT_ROOT = Path.home() / ".claude" / "projects"`.
  A parsed session dict has keys `session_id, title, project, cwd, branch, started_at,
  ended_at, original, turns` where `turns` is `list[{"role": "user"|"assistant", "at":
  str, "text": str}]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_claude.py
import json
from pathlib import Path

from archie.connectors.claude import mask_secrets, parse_session


def _write(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def user(text, **extra):
    return {"type": "user", "timestamp": "2026-10-09T16:02:11Z",
            "message": {"role": "user", "content": text}, **extra}


def assistant(text, **extra):
    return {"type": "assistant", "timestamp": "2026-10-09T16:03:40Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **extra}


def test_mask_secrets_covers_each_known_pattern():
    samples = {
        "sk-abcdefghijklmnopqrstuvwxyz0123456789": "Anthropic/OpenAI",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789": "GitHub",
        "AIzaSyD-abcdefghijklmnopqrstuvwxyz01234": "Google",
        "xoxb-1234567890-abcdefghij": "Slack",
    }
    for secret, label in samples.items():
        out = mask_secrets(f"here is my key: {secret} please use it")
        assert secret not in out and "[secret removed]" in out, label
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOg==\n-----END RSA PRIVATE KEY-----"
    out = mask_secrets(f"key:\n{pem}\nthanks")
    assert "MIIBOg==" not in out and "[secret removed]" in out


def test_mask_secrets_leaves_ordinary_text_alone():
    text = "Can you review the Redis fallback patch before Friday?"
    assert mask_secrets(text) == text


def test_parse_session_keeps_prompts_and_text_replies(tmp_path):
    path = _write(tmp_path, [
        user("I want to add Claude logs as a source for Archie.", cwd="/Users/test/code/archie",
             gitBranch="main"),
        assistant("Claude Code deletes its own logs after 30 days, so I recommend a slim copy."),
        {"type": "ai-title", "aiTitle": "Claude log retention period"},
    ])
    session = parse_session(path)
    assert session["title"] == "Claude log retention period"
    assert session["project"] == "archie" and session["branch"] == "main"
    assert session["session_id"] == "session"
    assert [t["role"] for t in session["turns"]] == ["user", "assistant"]
    assert session["turns"][0]["text"] == "I want to add Claude logs as a source for Archie."
    assert "slim copy" in session["turns"][1]["text"]
    assert session["started_at"] == "2026-10-09T16:02:11Z"
    assert session["ended_at"] == "2026-10-09T16:03:40Z"
    assert session["original"] == str(path)


def test_parse_session_drops_meta_sidechain_and_compaction(tmp_path):
    path = _write(tmp_path, [
        user("real prompt", cwd="/x/y"),
        {**user("dropped"), "isMeta": True},
        {**user("dropped"), "isSidechain": True},
        {**assistant("dropped"), "isCompactSummary": True},
        {"type": "file-history-snapshot", "snapshot": "…"},
    ])
    session = parse_session(path)
    assert len(session["turns"]) == 1 and session["turns"][0]["text"] == "real prompt"


def test_parse_session_collapses_a_slash_command(tmp_path):
    text = ("<local-command-caveat>The command below was run directly, not sent as a "
            "request.</local-command-caveat>\n<command-name>/clear</command-name>\n"
            "            <command-message>clear</command-message>\n"
            "            <command-args></command-args>\n<local-command-stdout></local-command-stdout>")
    path = _write(tmp_path, [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "/clear"


def test_parse_session_drops_wrapper_only_turns(tmp_path):
    path = _write(tmp_path, [
        user("<task-notification>a background task finished</task-notification>", cwd="/x/y"),
        user("[Request interrupted by user]", cwd="/x/y"),
        user("real prompt", cwd="/x/y"),
    ])
    session = parse_session(path)
    assert [t["text"] for t in session["turns"]] == ["real prompt"]


def test_parse_session_strips_system_reminders_but_keeps_the_rest(tmp_path):
    text = ("what should I work on?\n<system-reminder>background context the user "
            "didn't write</system-reminder>")
    path = _write(tmp_path, [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "what should I work on?"


def test_parse_session_skips_an_unparseable_line(tmp_path):
    path = tmp_path / "session.jsonl"
    good = json.dumps(user("real prompt", cwd="/x/y"))
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    session = parse_session(path)
    assert session["turns"][0]["text"] == "real prompt"


def test_parse_session_returns_none_with_no_kept_turns(tmp_path):
    path = _write(tmp_path, [{**user("dropped"), "isMeta": True}])
    assert parse_session(path) is None


def test_parse_session_masks_a_secret_in_a_prompt(tmp_path):
    path = _write(tmp_path, [user("here's my key sk-abcdefghijklmnopqrstuvwxyz0123456789", cwd="/x/y")])
    session = parse_session(path)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in session["turns"][0]["text"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_claude.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'archie.connectors.claude'`

- [ ] **Step 3: Write the implementation**

```python
# archie/connectors/claude.py
"""Claude Code session transcripts, read-only and local-only. One slim file per session:
sources/claude/<project>/<session_id>.json (DESIGN §5.1; design spec
docs/superpowers/specs/2026-10-09-claude-logs-source-design.md).

Claude Code deletes its own `.jsonl` logs after `cleanupPeriodDays` (default 30), so this
connector keeps a slim copy: each kept user prompt and assistant text reply, with secrets
masked, plus the session's title, project, branch and times. Tool calls, tool output,
attachments, file snapshots and compaction summaries are left out. A slim copy that
outlives its original is not treated as a deletion (DESIGN §4's tombstone rule doesn't
apply here): the original vanishing is Claude Code's own cleanup, not the user removing
anything.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from archie.connectors.base import SyncCtx, SyncResult
from archie.index.chunk import Chunk, chunk_windows, register_raw_chunker, short_date
from archie.store.files import write_raw

NAME = "claude"
DEFAULT_ROOT = Path.home() / ".claude" / "projects"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),                        # Anthropic / OpenAI
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),                   # GitHub
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                        # Google
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),                 # Slack
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_CAVEAT = re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.S)
_STDOUT = re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.S)
_TASK_NOTIF = re.compile(r"<task-notification>.*?</task-notification>", re.S)
_COMMAND = re.compile(
    r"<command-name>(.*?)</command-name>"
    r"(?:\s*<command-message>.*?</command-message>)?"
    r"(?:\s*<command-args>(.*?)</command-args>)?", re.S)
_INTERRUPTED = re.compile(r"^\[Request interrupted by user[^\]]*\]$", re.S)


def mask_secrets(text: str) -> str:
    """Replace anything that looks like a pasted API key or private key with a
    placeholder, so a transcript copy is always safe to commit (DESIGN §4)."""
    for pat in SECRET_PATTERNS:
        text = pat.sub("[secret removed]", text)
    return text


def _clean_user_text(raw: str) -> str:
    """A slash command collapses to "/name args". Harness wrappers (system reminders,
    task notifications, local-command caveats/output, interrupt markers) are dropped.
    Anything the user actually typed is kept as is."""
    m = _COMMAND.search(raw)
    if m:
        name, args = m.group(1).strip(), (m.group(2) or "").strip()
        return f"{name} {args}".strip()
    text = _SYSTEM_REMINDER.sub("", raw)
    text = _CAVEAT.sub("", text)
    text = _STDOUT.sub("", text)
    text = _TASK_NOTIF.sub("", text)
    text = text.strip()
    return "" if _INTERRUPTED.match(text) else text


def _turn_text(record: dict, role: str) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        raw = content
    else:
        raw = "\n".join(b.get("text", "") for b in content or []
                        if isinstance(b, dict) and b.get("type") == "text")
    raw = raw.strip()
    return _clean_user_text(raw) if role == "user" else raw


def parse_session(path: Path) -> dict | None:
    """One `.jsonl` log to a slim session dict, or `None` if it has no kept turns."""
    title = cwd = branch = None
    started = ended = None
    turns: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = record.get("type")
        if kind == "ai-title":
            title = record.get("aiTitle") or title
            continue
        if kind not in ("user", "assistant"):
            continue
        if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
            continue
        cwd = cwd or record.get("cwd")
        branch = branch or record.get("gitBranch")
        text = _turn_text(record, kind)
        if not text:
            continue
        ts = record.get("timestamp")
        turns.append({"role": kind, "at": ts, "text": mask_secrets(text)})
        started = started or ts
        ended = ts
    if not turns:
        return None
    project = PurePosixPath(cwd).name if cwd else "unknown"
    home = str(Path.home())
    original = str(path)
    if original.startswith(home):
        original = "~" + original[len(home):]
    return {"session_id": path.stem, "title": title, "project": project, "cwd": cwd,
            "branch": branch, "started_at": started, "ended_at": ended,
            "original": original, "turns": turns}
```

(The `ClaudeConnector` class and `chunk_session` come in Tasks 2 and 3 — this task only
needs the parsing/masking functions above to pass its tests. Add the remaining imports
`asyncio`, `timedelta`, `timezone` are already imported for later tasks' convenience;
unused-import lint will be satisfied once Tasks 2–3 land in the same file, so run this
task's test file directly rather than a whole-repo lint.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_claude.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add archie/connectors/claude.py tests/unit/test_claude.py
git commit -m "Claude sessions: parse logs into a slim, secret-masked session dict

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: The connector — sync, cursor, registration

**Files:**
- Modify: `archie/connectors/claude.py` (add `ClaudeConnector`)
- Modify: `archie/connectors/registry.py`
- Test: `tests/unit/test_claude.py` (append)

**Interfaces:**
- Consumes: `parse_session(path) -> dict | None` and `NAME`, `DEFAULT_ROOT` from Task 1.
- Produces: `class ClaudeConnector` with `name = NAME` and
  `async def sync(self, sctx: SyncCtx, cursor) -> SyncResult`, matching
  `archie/connectors/base.py`'s `Connector` protocol exactly (same shape as
  `JiraConnector`/`GitHubConnector`).

- [ ] **Step 1: Write the failing tests**

```python
# appended to tests/unit/test_claude.py
import asyncio

from archie.config import Me
from archie.connectors.base import SyncCtx
from archie.connectors.claude import ClaudeConnector
from archie.store.files import read_raw
from archie.store.home import init_home

NOW = __import__("datetime").datetime(2026, 10, 9, 18, 0, tzinfo=__import__("datetime").timezone.utc)
ME = Me(name="Test")


def _project_dir(tmp_path, name="archie"):
    d = tmp_path / "claude_logs" / name
    d.mkdir(parents=True)
    return d


def run(log_root, cursor=None, home_path=None, now=NOW):
    home = init_home(home_path)
    sctx = SyncCtx(home, {"path": str(log_root)}, ME, now)
    res = asyncio.run(ClaudeConnector().sync(sctx, cursor))
    return home, res


def test_sync_writes_one_raw_file_per_session(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "s1.jsonl", [user("hello", cwd="/Users/test/code/archie")])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1
    data = read_raw(home / "sources/claude/archie/s1.json")
    assert data["turns"][0]["text"] == "hello"


def test_sync_skips_subagent_logs(tmp_path):
    proj = _project_dir(tmp_path)
    (proj / "subagents").mkdir()
    _write(proj / "subagents" / "sub1.jsonl", [user("subagent prompt", cwd="/x/y")])
    _write(proj / "main.jsonl", [user("main prompt", cwd="/x/y")])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1
    assert read_raw(home / "sources/claude/y/main.json")["turns"][0]["text"] == "main prompt"


def test_sync_skips_a_session_with_no_kept_turns(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "empty.jsonl", [{**user("dropped"), "isMeta": True}])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert res.written == []


def test_first_sync_takes_every_log_regardless_of_age(tmp_path):
    import os
    import time

    proj = _project_dir(tmp_path)
    old = proj / "old.jsonl"
    _write(old, [user("from a month ago", cwd="/x/y")])
    month_ago = time.time() - 31 * 86400
    os.utime(old, (month_ago, month_ago))
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1  # no cursor yet: everything on disk is taken


def test_incremental_sync_only_rewrites_a_changed_session(tmp_path):
    import os
    from datetime import timedelta

    # File mtimes are real wall-clock epoch times, but `since` is computed from the
    # simulated `now` passed to the connector — so the test pins both logs' mtimes onto
    # that same simulated timeline with os.utime, rather than relying on how fast the
    # test happens to run in real time.
    proj = _project_dir(tmp_path)
    s1 = proj / "s1.jsonl"
    _write(s1, [user("first", cwd="/x/y")])
    os.utime(s1, ((NOW - timedelta(hours=3)).timestamp(),) * 2)  # well before the next cursor's cutoff
    home, res1 = run(tmp_path / "claude_logs", home_path=tmp_path / "home", now=NOW)
    cursor = {"last_sync": res1.cursor["last_sync"]}

    later = NOW + timedelta(hours=2)
    s2 = proj / "s2.jsonl"
    _write(s2, [user("second", cwd="/x/y")])
    os.utime(s2, (later.timestamp(),) * 2)  # after the next cursor's cutoff (last_sync - 1h = NOW - 1h)

    home2, res2 = run(tmp_path / "claude_logs", cursor=cursor, home_path=tmp_path / "home", now=later)
    assert len(res2.written) == 1
    assert "s2.json" in str(res2.written[0])


def test_missing_log_folder_raises_a_plain_error(tmp_path):
    try:
        run(tmp_path / "nope", home_path=tmp_path / "home")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "isn't there" in str(exc)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_claude.py -v -k sync`
Expected: FAIL with `ImportError: cannot import name 'ClaudeConnector'`

- [ ] **Step 3: Add `ClaudeConnector` to `archie/connectors/claude.py`**

```python
# appended to archie/connectors/claude.py


class ClaudeConnector:
    name = NAME

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        root = Path(sctx.config.get("path") or DEFAULT_ROOT).expanduser()
        if not root.exists():
            raise RuntimeError(f"Claude Code's log folder {root} isn't there")
        last_sync = cursor.get("last_sync")
        since = (datetime.fromisoformat(last_sync) - timedelta(hours=1)) if last_sync else None
        written = []
        for log in sorted(root.glob("*/*.jsonl")):
            if "subagents" in log.parts:
                continue
            mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
            if since and mtime < since:
                continue
            session = parse_session(log)
            if session is None:
                continue
            out = sctx.source_dir(NAME) / session["project"] / f"{session['session_id']}.json"
            write_raw(out, session)
            written.append(out)
        return SyncResult(cursor={"last_sync": sctx.now.isoformat()}, written=written)
```

- [ ] **Step 4: Register it in the connector registry**

Modify `archie/connectors/registry.py`:

```python
from archie.connectors.calendar import CalendarConnector
from archie.connectors.claude import ClaudeConnector
from archie.connectors.drive import DriveConnector
from archie.connectors.github import GitHubConnector
from archie.connectors.gmail import GmailConnector
from archie.connectors.jira import JiraConnector

ALL = {"gmail": GmailConnector, "calendar": CalendarConnector, "drive": DriveConnector,
       "github": GitHubConnector, "jira": JiraConnector, "claude": ClaudeConnector}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_claude.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add archie/connectors/claude.py archie/connectors/registry.py tests/unit/test_claude.py
git commit -m "Claude sessions: connector sync, cursor and registry entry

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Chunking — one chunk per exchange

**Files:**
- Modify: `archie/connectors/claude.py` (add `chunk_session` + `register_raw_chunker` call)
- Modify: `archie/index/chunk.py` (bump `CHUNKER_VERSION`)
- Test: `tests/unit/test_claude.py` (append)

**Interfaces:**
- Consumes: `Chunk`, `chunk_windows`, `register_raw_chunker`, `short_date` from
  `archie.index.chunk` (all already public module-level names); `chunk_file(path, text)`
  from `archie.index.chunk` for the integration test.
- Produces: `chunk_session(path: str, data: dict) -> list[Chunk]`, registered for
  `NAME = "claude"` so `chunk_file` dispatches to it for any `sources/claude/**/*.json`
  path.

- [ ] **Step 1: Write the failing tests**

```python
# appended to tests/unit/test_claude.py
from archie.index.chunk import chunk_file


def test_chunk_session_groups_one_user_turn_with_its_replies(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "s1.jsonl", [
        user("first question", cwd="/Users/test/code/archie"),
        assistant("first answer, part one"),
        assistant("first answer, part two"),
        user("second question"),
        assistant("second answer"),
        {"type": "ai-title", "aiTitle": "Two questions"},
    ])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    rel = "sources/claude/archie/s1.json"
    chunks = chunk_file(rel, (home / rel).read_text())
    assert len(chunks) == 2
    assert chunks[0].chunk_id == "c0-0" and chunks[1].chunk_id == "c1-0"
    assert "first question" in chunks[0].text and "first answer, part one" in chunks[0].text
    assert "first answer, part two" in chunks[0].text
    assert "second question" in chunks[1].text and "second answer" in chunks[1].text
    assert "first question" not in chunks[1].text


def test_chunk_session_label_has_title_project_and_date(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "s1.jsonl", [
        user("q", cwd="/Users/test/code/archie"),
        assistant("a"),
        {"type": "ai-title", "aiTitle": "Claude log retention period"},
    ])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    rel = "sources/claude/archie/s1.json"
    chunks = chunk_file(rel, (home / rel).read_text())
    assert chunks[0].label == "Claude session: Claude log retention period (archie, Oct 9)"


def test_chunk_session_label_without_a_title(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "s1.jsonl", [user("q", cwd="/Users/test/code/archie"), assistant("a")])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    rel = "sources/claude/archie/s1.json"
    chunks = chunk_file(rel, (home / rel).read_text())
    assert chunks[0].label == "Claude session in archie (Oct 9)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_claude.py -v -k chunk_session`
Expected: FAIL — `chunk_file` returns `[]` (no chunker registered for `claude`)

- [ ] **Step 3: Add `chunk_session` and register it**

```python
# appended to archie/connectors/claude.py


def chunk_session(path: str, data: dict) -> list[Chunk]:
    """One chunk per exchange: a user turn plus the assistant turns up to the next user
    turn (DESIGN §5.3). Assistant turns before the first user turn join the first
    exchange. An exchange over 280 words splits like any other chunk."""
    turns = data.get("turns") or []
    title, project = data.get("title"), data.get("project") or "unknown"
    groups: list[list[dict]] = []
    for turn in turns:
        if turn["role"] == "user" or not groups:
            groups.append([turn])
        else:
            groups[-1].append(turn)
    out: list[Chunk] = []
    for i, group in enumerate(groups):
        date = short_date(group[0]["at"])
        label = (f"Claude session: {title} ({project}, {date})" if title
                 else f"Claude session in {project} ({date})")
        text = "\n".join(f"{'You' if t['role'] == 'user' else 'Claude'}: {t['text']}" for t in group)
        for j, chunk in enumerate(chunk_windows(path, text, source=NAME, ts=group[0]["at"])):
            chunk.chunk_id, chunk.label = f"c{i}-{j}", label
            out.append(chunk)
    return out


register_raw_chunker(NAME, chunk_session)
```

- [ ] **Step 4: Bump `CHUNKER_VERSION`**

Modify `archie/index/chunk.py:14`:

```python
CHUNKER_VERSION = "5"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_claude.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add archie/connectors/claude.py archie/index/chunk.py tests/unit/test_claude.py
git commit -m "Claude sessions: chunk one exchange at a time

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Activity — Claude sessions in the standup, ledger and journal

**Files:**
- Modify: `archie/activity.py`
- Test: `tests/unit/test_activity_claude.py`

**Interfaces:**
- Consumes: `Item` dataclass (`when, kind, title, project, path, chunk, quote`) and
  `KIND_WORDS` dict, both already in `archie/activity.py`; `read_raw` from
  `archie.store.files`.
- Produces: `KIND_WORDS["claude_session"] = "Claude sessions"`; `my_activity` emits one
  `Item(kind="claude_session", ...)` per session that has at least one user turn inside
  the window.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_activity_claude.py
from datetime import datetime, timezone

from archie.activity import my_activity
from archie.ask.context import Ctx
from archie.config import Me, load_config
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.llm.backend import FakeBackend
from archie.store.files import write_raw
from archie.store.home import init_home

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def _ctx(tmp_path):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    return Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)


def test_a_claude_session_counts_once_for_its_first_in_window_user_turn(tmp_path):
    ctx = _ctx(tmp_path)
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": "Claude log retention period", "project": "archie",
        "cwd": "/x", "branch": "main", "started_at": "2026-10-09T16:02:11Z",
        "ended_at": "2026-10-09T16:03:40Z", "original": "/x/s1.jsonl",
        "turns": [{"role": "user", "at": "2026-10-09T16:02:11Z",
                   "text": "okay, now I want to add claude logs as a source"},
                  {"role": "assistant", "at": "2026-10-09T16:03:40Z", "text": "Before going further…"},
                  {"role": "user", "at": "2026-10-09T17:00:00Z", "text": "looks good"}]})
    start, end = datetime(2026, 10, 9, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc)
    items = [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"]
    assert len(items) == 1
    assert items[0].title == "Claude log retention period" and items[0].project == "archie"
    assert items[0].path == "sources/claude/archie/s1.json" and items[0].chunk == "c0-0"
    assert items[0].when == "2026-10-09T16:02:11Z"


def test_a_session_entirely_outside_the_window_is_not_an_item(tmp_path):
    ctx = _ctx(tmp_path)
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": None, "project": "archie", "cwd": "/x", "branch": "main",
        "started_at": "2026-09-01T00:00:00Z", "ended_at": "2026-09-01T00:01:00Z", "original": "/x/s1.jsonl",
        "turns": [{"role": "user", "at": "2026-09-01T00:00:00Z", "text": "old session"}]})
    start, end = datetime(2026, 10, 9, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_activity_claude.py -v`
Expected: FAIL — no `claude_session` items are produced

- [ ] **Step 3: Implement in `archie/activity.py`**

Modify the `KIND_WORDS` dict at the top of the file:

```python
KIND_WORDS = {"commit": "Commits", "pr_merged": "PRs merged", "pr_opened": "PRs opened", "review_given": "Reviews",
              "issue_done": "Issues closed", "transition": "Issues moved", "doc_edited": "Docs edited",
              "email_sent": "Emails sent", "meeting": "Meetings", "claude_session": "Claude sessions"}
```

Add a loop in `my_activity`, right before the `from archie.derive.meetings import load_meetings` line:

```python
    for p in sorted((ctx.home / "sources/claude").rglob("*.json")):
        d = read_raw(p)
        group = -1
        for t in d.get("turns") or []:
            if t["role"] == "user":
                group += 1
            if t["role"] == "user" and _in(t.get("at"), start, end):
                title = d.get("title") or "Claude session"
                quote = (t.get("text") or title).splitlines()[0]
                out.append(Item(t["at"], "claude_session", title, d.get("project") or "", _rel(ctx, p),
                                f"c{group}-0", quote))
                break
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_activity_claude.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full activity test suite to check nothing else broke**

Run: `python -m pytest tests/unit/test_activity_claude.py tests/vignettes/test_m3.py tests/vignettes/test_m4.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add archie/activity.py tests/unit/test_activity_claude.py
git commit -m "Claude sessions: count as activity in the standup, ledger and journal

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `show N` names the original log, or says it's gone

**Files:**
- Modify: `archie/ask/followup.py`
- Test: `tests/unit/test_followup_claude.py`

**Interfaces:**
- Consumes: `show(ctx, last, n) -> Answer` (existing signature, unchanged); `read_raw`
  from `archie.store.files`.
- Produces: no interface change — `show()`'s returned `Answer.plain` gains one extra
  line when `c["file"]` starts with `"sources/claude/"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_followup_claude.py
from archie.ask.followup import show
from archie.ask.context import Ctx
from archie.config import Me, load_config
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.llm.backend import FakeBackend
from archie.store.files import atomic_write, write_raw
from archie.store.home import init_home
from datetime import datetime, timezone

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def _ctx_with_session(tmp_path, original_exists: bool):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    ctx = Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)
    original = tmp_path / "original.jsonl"
    if original_exists:
        atomic_write(original, "{}\n")
    write_raw(ctx.home / "sources/claude/archie/s1.json", {
        "session_id": "s1", "title": "Claude log retention period", "project": "archie",
        "cwd": "/x", "branch": "main", "started_at": "2026-10-09T16:02:11Z",
        "ended_at": "2026-10-09T16:03:40Z", "original": str(original),
        "turns": [{"role": "user", "at": "2026-10-09T16:02:11Z", "text": "when did we decide this?"},
                  {"role": "assistant", "at": "2026-10-09T16:03:40Z",
                   "text": "I recommend a slim copy instead of a symlink."}]})
    ctx.index.sync()
    return ctx


def _last(quote):
    return {"citations": [{"n": 1, "file": "sources/claude/archie/s1.json", "chunk": "c0-0",
                           "label": "Claude session: Claude log retention period (archie, Oct 9)",
                           "quote": quote}]}


def test_show_names_the_original_log_when_it_still_exists(tmp_path):
    ctx = _ctx_with_session(tmp_path, original_exists=True)
    out = show(ctx, _last("I recommend a slim copy instead of a symlink."), 1).plain
    assert "Full log:" in out and "original.jsonl" in out


def test_show_says_the_log_was_cleaned_up_once_it_is_gone(tmp_path):
    ctx = _ctx_with_session(tmp_path, original_exists=False)
    out = show(ctx, _last("I recommend a slim copy instead of a symlink."), 1).plain
    assert "removed by Claude Code's 30-day cleanup" in out


def test_show_on_a_non_claude_citation_is_unaffected(tmp_path):
    home = init_home(tmp_path / "home")
    cfg = load_config(home)
    cfg["index"]["embed_model"] = "hash"
    ctx = Ctx(home=home, config=cfg, me=Me(name="Test"), index=Index(home, HashEmbedder()),
              backend=FakeBackend([]), now=NOW)
    atomic_write(ctx.home / "people/alex.md", "---\nname: Alex\n---\n## My notes\nPrefers snippets.\n")
    ctx.index.sync()
    last = {"citations": [{"n": 1, "file": "people/alex.md", "chunk": "c1", "label": "Alex (dossier)",
                           "quote": "Prefers snippets."}]}
    out = show(ctx, last, 1).plain
    assert "Full log" not in out and "cleanup" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_followup_claude.py -v`
Expected: the two Claude-citation tests FAIL (no "Full log" / "cleanup" line yet)

- [ ] **Step 3: Implement in `archie/ask/followup.py`**

Add near the top, with the other imports:

```python
from archie.store.files import read_raw
```

Modify the `show` function (the existing body up to `lines += ["", c["file"]]` is
unchanged; add the new block right after it, before `markdown = ...`):

```python
def show(ctx: Ctx, last: dict | None, n: int) -> Answer:
    cites = (last or {}).get("citations") or []
    if not cites:
        return Answer(plain="There's no recent answer with sources to show.")
    c = next((c for c in cites if c.get("n") == n), None)
    if c is None:
        return Answer(plain=f"The last answer has citations 1–{len(cites)}.")
    lines = [f"[{n}] {c.get('label') or c['file']}", f"“{c.get('quote', '')}”"]
    around = _around(ctx.index.chunk_text(c["file"], c["chunk"]) or "", c.get("quote", ""))
    if around:
        lines += ["", around]
    lines += ["", c["file"]]
    if c["file"].startswith("sources/claude/"):
        from pathlib import Path

        data = read_raw(ctx.home / c["file"])
        original = Path(data.get("original", "")).expanduser()
        if original.exists():
            lines.append(f"Full log: {data['original']}")
        else:
            lines.append("The full log was removed by Claude Code's 30-day cleanup; this is Archie's copy.")
    markdown = around if around and c["file"].endswith(".md") else None
    return Answer(plain="\n".join(lines), markdown=markdown)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_followup_claude.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the existing follow-up vignette to check nothing broke**

Run: `python -m pytest tests/vignettes/test_o_followups.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add archie/ask/followup.py tests/unit/test_followup_claude.py
git commit -m "show N: name the original Claude log, or say it was cleaned up

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end vignette — "what did Claude and I decide?"

**Files:**
- Create: `tests/vignettes/test_y_claude_sessions.py`

**Interfaces:**
- Consumes: `make_ctx` from `tests.support.fixtures`; `ClaudeConnector` and `SyncCtx` from
  Task 2; `ask`/`render` from `archie.ask.pipeline`/`archie.ask.render`; `my_activity`
  from `archie.activity`; `FakeBackend` from `archie.llm.backend`; `understood`/
  `question` from `tests.support.fixtures`.

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/vignettes/test_y_claude_sessions.py
"""Vignette Y (docs/VIGNETTES.md): what did Claude and I decide?"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.connectors.base import SyncCtx
from archie.connectors.claude import ClaudeConnector
from archie.activity import my_activity
from archie.llm.backend import FakeBackend
from tests.support.fixtures import make_ctx, question, understood

ASSISTANT_REPLY = "Claude Code deletes its own logs after 30 days, so I recommend a slim copy instead of a symlink."


def _write_log(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _session_records():
    return [
        {"type": "user", "timestamp": "2026-10-09T16:02:11Z", "cwd": "/Users/test/code/archie",
         "gitBranch": "main", "message": {"role": "user", "content":
         "okay, now I want to add claude logs as a source for Archie, with sync and indexing"}},
        {"type": "assistant", "timestamp": "2026-10-09T16:03:40Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": ASSISTANT_REPLY}]}},
        {"type": "ai-title", "aiTitle": "Claude log retention period"},
    ]


def model(system, user, shape, tier):
    if shape.name == "understand":
        return understood(question("search", topic="log retention"))
    return {"summary": [{"text": "A slim copy was recommended over a symlink.",
                         "citations": [{"ref": 1, "quote": ASSISTANT_REPLY}]}],
            "sections": []}


def test_Y_ask_cites_the_claude_exchange(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb, now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    _write_log(log_root / "df9db305.jsonl", _session_records())

    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))
    ctx.index.sync()

    out = render(ask(ctx, "when did we talk about log retention?"), sources=True, paths=True)
    assert "[1]" in out
    assert "sources/claude/archie/df9db305.json" in out
    assert "Claude session: Claude log retention period (archie, Oct 9)" in out


def test_Y_a_session_shows_up_in_the_days_activity(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]), now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    _write_log(log_root / "df9db305.jsonl", _session_records())
    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))

    start = datetime(2026, 10, 9, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    items = [i for i in my_activity(ctx, start, end) if i.kind == "claude_session"]
    assert len(items) == 1 and items[0].title == "Claude log retention period"


def test_Y_deleting_the_original_keeps_the_copy_and_its_index_entry(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]), now=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc))
    log_root = tmp_path / "claude_logs" / "archie"
    log_path = log_root / "df9db305.jsonl"
    _write_log(log_path, _session_records())
    sctx = SyncCtx(ctx.home, {"path": str(tmp_path / "claude_logs")}, ctx.me, ctx.now)
    asyncio.run(ClaudeConnector().sync(sctx, None))
    ctx.index.sync()

    log_path.unlink()  # Claude Code's 30-day cleanup
    ctx.index.sync()  # a later sync must not drop the slim copy: nothing in sources/claude/ changed

    rel = "sources/claude/archie/df9db305.json"
    assert (ctx.home / rel).exists()
    assert ctx.index.chunk_text(rel, "c0-0")
```

- [ ] **Step 2: Run the test to verify it currently fails or passes**

Run: `python -m pytest tests/vignettes/test_y_claude_sessions.py -v`
Expected: all 3 PASS (every piece was already built and tested in Tasks 1–4; this test
only exercises them together end to end). If any fails, re-check that Task 1–4 code is
present and committed before continuing.

- [ ] **Step 3: Run the whole test suite**

Run: `python -m pytest -q`
Expected: all passed, no regressions in the other vignettes

- [ ] **Step 4: Commit**

```bash
git add tests/vignettes/test_y_claude_sessions.py
git commit -m "Vignette Y: end-to-end test for Claude sessions as a source

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Docs and OKF

**Files:**
- Modify: `docs/DESIGN.md`
- Modify: `docs/VIGNETTES.md`
- Modify: `okf/components/connectors.md`
- Modify: `okf/components/activity.md`
- Modify: `okf/log.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: `docs/DESIGN.md` §4 storage layout**

Add one line to the `sources/` block (after the `jira/<KEY-123>.json` line):

```
│   ├── github/<owner>__<repo>/pr-<n>.json, commits/<sha>.json
│   ├── jira/<KEY-123>.json
│   └── claude/<project>/<session_id>.json  # slim copy of a Claude Code session; the
│                                            # original .jsonl log is deleted by Claude
│                                            # Code after 30 days, this copy is not
```

- [ ] **Step 2: `docs/DESIGN.md` §5.1 connectors table and rules**

Add a row to the connectors table:

```
| Claude   | —     | file mtime since last sync (local, no API)   | session (one `.jsonl` log) |
```

Add a paragraph right after the table's existing rules:

> **Claude Code sessions are a local, no-backfill-limit exception.** The source is the
> user's own `~/.claude/projects` logs, which Claude Code itself deletes after
> `cleanupPeriodDays` (default 30 days). So the first sync takes every log on disk
> instead of the usual 14-day backfill, and when Claude Code's own cleanup removes a log,
> the slim copy already written is kept and indexed rather than tombstoned — the
> deletion is Claude Code's housekeeping, not the user removing something.

- [ ] **Step 3: `docs/DESIGN.md` §5.3 chunking table**

Add a row:

```
| Claude session    | one chunk per exchange: a user turn plus the assistant turns up to the next user turn |
```

- [ ] **Step 4: `docs/VIGNETTES.md` coverage table and new vignette**

Add a row to the Coverage table (after row X):

```
| Y | What did Claude and I decide? | Claude Code logs → connector, chunker, activity | M5 | ✅ |
```

Add a new section after `## X. Plans I tell Archie`:

```markdown
## Y. What did Claude and I decide?

**Situation.** Weeks later, the user half-remembers a decision made in a Claude Code
session but not where.

**User:** `ask "when did we talk about log retention?"`

**Archie shows:** a short summary citing the exchange, labelled with the session's
title, project and date — "Claude session: Claude log retention period (archie, Oct 9)".

**What happens.** Claude Code's own session logs (`~/.claude/projects`) are mirrored as
a slim, secret-masked copy (prompts and text replies only — no tool calls, attachments or
compaction summaries) to `sources/claude/<project>/<session_id>.json`, chunked one
exchange at a time, and found through the same hybrid search as every other source.
Sessions also count as activity: they show up in catch-up, the standup, the weekly brag
doc and the review ledger.

**Acceptance:** the exchange is found and cited with its session's title/project/date;
nothing from tool output or Claude's internal thinking leaks into a chunk; a deleted
original log still has a working citation. Tests: `tests/vignettes/test_y_claude_sessions.py`.
```

- [ ] **Step 5: `okf/components/connectors.md`**

Add a bullet after the `jira.py` bullet, before the closing summary line:

```markdown
- `claude.py`: reads the user's local Claude Code session logs (`~/.claude/projects/**/*.jsonl`, no network). Writes a slim, secret-masked copy per session — prompts, assistant text replies, title, project, branch, times — to `sources/claude/<project>/<session_id>.json`. Tool calls, attachments, file-history snapshots, subagent logs and compaction summaries are left out. Cursor: file mtime since the last sync; the **first sync takes every log on disk**, because Claude Code deletes logs after `cleanupPeriodDays` (default 30) and anything older would be gone within days. A slim copy outlives its deleted original rather than becoming a tombstone. The chunker makes one chunk per exchange (a user turn plus the assistant turns up to the next one), labeled "Claude session: Title (project, Oct 9)".
```

Update the closing line:

```markdown
All phase-1 connectors are built, plus the local Claude Code sessions source. Phase 2: Slack. Design: [DESIGN §5.1](../../docs/DESIGN.md#51-connectors). Principles: [read-only](../principles/read-only.md), [keep everything](../principles/keep-everything.md). Each cycle is run by [sync](sync.md).
```

- [ ] **Step 6: `okf/components/activity.md`**

Add a row to the Kind table:

```markdown
| `claude_session` | a Claude Code session with a prompt in the window |
```

- [ ] **Step 7: `okf/log.md`**

Add a dated entry at the top:

```markdown
## 2026-10-09
- Claude Code sessions as a source (new connector [connectors](components/connectors.md), vignette Y, [spec](../docs/superpowers/specs/2026-10-09-claude-logs-source-design.md)). Measured: a symlink into `~/.claude/projects` would dangle after 30 days (Claude Code's own cleanup), and the raw logs are 98% tool output/attachments by size. `claude.py` mirrors a slim, secret-masked copy (prompts, text replies, title/project/branch/times) to `sources/claude/<project>/<session_id>.json`, chunked one exchange at a time. First sync takes every log on disk (an exception to the usual 14-day backfill); a slim copy outlives its deleted original rather than being tombstoned. Sessions also count in [activity](components/activity.md)'s standup/ledger/journal feeds, and `show N` on a Claude citation names the original log or says it was cleaned up.
```

- [ ] **Step 8: Run the OKF checker**

Run: `python3 scripts/okf_check.py`
Expected: exits 0, no errors

- [ ] **Step 9: Commit**

```bash
git add docs/DESIGN.md docs/VIGNETTES.md okf/components/connectors.md okf/components/activity.md okf/log.md
git commit -m "Docs: Claude Code sessions as a source (DESIGN, vignette Y, OKF)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final check

- [ ] Run `python -m pytest -q` once more from the repo root: all tests pass.
- [ ] Run `python3 scripts/okf_check.py`: exits 0.
- [ ] Manually enable the connector in `~/.archie/config.yaml` (`connectors: {claude: {enabled: true}}`)
  and run one real sync (`archie` TUI or the admin sync command) to confirm it reads the
  user's actual `~/.claude/projects` without error, before considering the feature live.
