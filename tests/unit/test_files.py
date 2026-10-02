import json
import os

import pytest

from archie.store.files import Note, atomic_write, read_note, read_raw, tombstone, write_note, write_raw


def test_atomic_write_creates_parents_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "a" / "b" / "note.md"
    atomic_write(target, "hello\n")
    assert target.read_text() == "hello\n"
    assert os.listdir(target.parent) == ["note.md"]


def test_atomic_write_failure_keeps_old_content(tmp_path, monkeypatch):
    target = tmp_path / "note.md"
    target.write_text("original\n")

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(target, "new\n")
    assert target.read_text() == "original\n"
    assert os.listdir(tmp_path) == ["note.md"]


def test_note_round_trip_keeps_key_order_and_body(tmp_path):
    path = tmp_path / "p.md"
    note = Note(meta={"type": "Person", "name": "Alex Rivera", "aliases": ["alexr"]}, body="## My notes\nhi\n")
    write_note(path, note)
    text = path.read_text()
    assert text.startswith("---\ntype: Person\nname: Alex Rivera\n")
    assert read_note(path) == note


def test_read_note_without_frontmatter(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("just text\n")
    assert read_note(path) == Note(meta={}, body="just text\n")


def test_note_keeps_unicode_and_dates_as_strings(tmp_path):
    path = tmp_path / "u.md"
    write_note(path, Note(meta={"name": "Zoë", "first_seen": "2026-10-01T16:02:00Z"}, body=""))
    meta = read_note(path).meta
    assert meta == {"name": "Zoë", "first_seen": "2026-10-01T16:02:00Z"}


def test_raw_round_trip_is_stable_json(tmp_path):
    path = tmp_path / "sources" / "gmail" / "t1.json"
    write_raw(path, {"b": 1, "a": "é"})
    assert read_raw(path) == {"b": 1, "a": "é"}
    first = path.read_text()
    write_raw(path, {"b": 1, "a": "é"})
    assert path.read_text() == first  # same input, same bytes (hash-stable for the indexer)


def test_tombstone_marks_deleted_and_keeps_payload(tmp_path):
    path = tmp_path / "t1.json"
    write_raw(path, {"id": "t1", "subject": "hi"})
    tombstone(path, "2026-10-02T00:00:00Z")
    data = json.loads(path.read_text())
    assert data["deleted"] is True
    assert data["deleted_at"] == "2026-10-02T00:00:00Z"
    assert data["subject"] == "hi"


def test_tombstone_on_missing_file_writes_minimal_marker(tmp_path):
    path = tmp_path / "gone.json"
    tombstone(path, "2026-10-02T00:00:00Z")
    assert read_raw(path) == {"deleted": True, "deleted_at": "2026-10-02T00:00:00Z"}
