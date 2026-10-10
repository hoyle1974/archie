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
