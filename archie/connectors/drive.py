"""Google Drive, read-only. Google Docs as plain text in sources/drive/<fileId>.json.

Which docs: ones the user owns or last edited, plus any doc attached to a calendar event
(read from the local calendar mirror). First sync lists docs modified in the backfill
window; after that the changes feed (page token) returns only what changed.
"""

from __future__ import annotations

import asyncio

from archie.connectors.base import SyncCtx, SyncResult
from archie.connectors.google_retry import execute
from archie.index.chunk import chunk_windows, register_raw_chunker, short_date
from archie.store.files import read_raw, tombstone, write_raw

NAME = "drive"
DOC = "application/vnd.google-apps.document"
FIELDS = "id,name,mimeType,modifiedTime,trashed,webViewLink,owners(emailAddress,displayName),lastModifyingUser(emailAddress,displayName)"
MAX_CHARS = 200_000


def _attached(sctx: SyncCtx) -> set[str]:
    ids = set()
    for p in sctx.source_dir("calendar").glob("*.json"):
        data = read_raw(p)
        ids |= {a["file_id"] for a in data.get("attachments", []) if a.get("file_id")}
    return ids


class DriveConnector:
    name = NAME
    after = ("calendar",)  # reads calendar attachments from the local mirror

    def __init__(self, service_factory=None):
        self._factory = service_factory

    def _service(self):
        if self._factory:
            return self._factory()
        from archie.connectors.google_auth import service

        return service("drive", "v3", "drive")

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _wanted(self, f: dict, sctx: SyncCtx, attached: set[str]) -> bool:
        if f.get("mimeType") != DOC or f.get("trashed"):
            return False
        mine = any(sctx.me.is_me(o.get("emailAddress", "")) for o in f.get("owners") or [])
        edited = sctx.me.is_me((f.get("lastModifyingUser") or {}).get("emailAddress", ""))
        return mine or edited or f["id"] in attached

    def _write(self, svc, f: dict, sctx: SyncCtx, attached: set[str]):
        text = execute(svc.files().export(fileId=f["id"], mimeType="text/plain"))
        text = (text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)).lstrip("﻿")
        path = sctx.source_dir(NAME) / f"{f['id']}.json"
        write_raw(path, {
            "id": f["id"], "title": f.get("name", ""), "mime": f.get("mimeType"), "modified": f.get("modifiedTime"),
            "modified_by": (f.get("lastModifyingUser") or {}).get("emailAddress", "").lower(),
            "modified_by_name": (f.get("lastModifyingUser") or {}).get("displayName", ""),
            "owners": [o.get("emailAddress", "").lower() for o in f.get("owners") or []],
            "link": f.get("webViewLink", ""), "attached_to_meeting": f["id"] in attached,
            "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS})
        return path

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        svc = self._service()
        attached = _attached(sctx)
        written, deleted = [], []
        if not cursor.get("page_token"):
            token = execute(svc.changes().getStartPageToken())["startPageToken"]
            q = f"mimeType = '{DOC}' and trashed = false and modifiedTime > '{sctx.backfill_start.strftime('%Y-%m-%dT%H:%M:%S')}'"
            req, files = svc.files().list(q=q, fields=f"nextPageToken,files({FIELDS})", pageSize=200), []
            while req is not None:
                resp = execute(req)
                files += resp.get("files", [])
                req = svc.files().list_next(req, resp)
            for fid in attached - {f["id"] for f in files}:
                try:
                    files.append(execute(svc.files().get(fileId=fid, fields=FIELDS)))
                except Exception:
                    continue  # no access to that attachment
            for f in files:
                if self._wanted(f, sctx, attached):
                    written.append(self._write(svc, f, sctx, attached))
            return SyncResult(cursor={"page_token": token}, written=written)
        req, token = svc.changes().list(pageToken=cursor["page_token"], fields=f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FIELDS}))"), cursor["page_token"]
        while req is not None:
            resp = execute(req)
            for ch in resp.get("changes", []):
                path = sctx.source_dir(NAME) / f"{ch['fileId']}.json"
                f = ch.get("file") or {}
                if ch.get("removed") or f.get("trashed"):
                    if path.exists() and not read_raw(path).get("deleted"):
                        tombstone(path, sctx.now.isoformat())
                        deleted.append(path)
                elif self._wanted(f, sctx, attached):
                    written.append(self._write(svc, f, sctx, attached))
            token = resp.get("newStartPageToken") or token
            req = svc.changes().list_next(req, resp)
        mirrored = {p.stem for p in sctx.source_dir(NAME).glob("*.json")}
        for fid in sorted(attached - mirrored):  # attachments seen since the last Drive sync
            try:
                f = execute(svc.files().get(fileId=fid, fields=FIELDS))
            except Exception:
                continue
            if self._wanted(f, sctx, attached):
                written.append(self._write(svc, f, sctx, attached))
        return SyncResult(cursor={"page_token": token}, written=written, deleted=deleted)


def chunk_doc(path: str, data: dict) -> list:
    label = f"Doc: {data.get('title')} (edited {short_date(data.get('modified'))})"
    people = sorted({data.get("modified_by", ""), *data.get("owners", [])} - {""})
    head = f"Document: {data.get('title')}\n"
    chunks = chunk_windows(path, head + data.get("text", ""), source=NAME, ts=data.get("modified"))
    for c in chunks:
        c.label, c.people, c.char_start, c.char_end = label, people, 0, 0
    return chunks


register_raw_chunker(NAME, chunk_doc)
