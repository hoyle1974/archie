
from archie.index.chunk import Chunk, register_raw_chunker
from archie.index.db import Index
from archie.index.embed import HashEmbedder
from archie.index.search import rrf, search
from archie.store.files import atomic_write, write_raw
from archie.store.home import init_home


def _mail_chunker(path, data):
    return [Chunk("c0", path, 0, 0, f"{data['subject']}\n{data['body']}", source="mailtest", ts=data["ts"])]


register_raw_chunker("mailtest", _mail_chunker)


def make_home(tmp_path):
    home = init_home(tmp_path / "home")
    atomic_write(home / "people/alex_rivera.md", "---\nname: Alex Rivera\n---\n## Notes\nOwns the Redis fallback work.\n")
    write_raw(home / "sources/mailtest/t1.json",
              {"subject": "ENG-402 token expiry", "body": "Can you review the patch?", "ts": "2026-10-01T09:00:00Z"})
    write_raw(home / "sources/mailtest/t2.json",
              {"subject": "Lunch", "body": "Tacos on Friday", "ts": "2026-09-01T09:00:00Z"})
    return home


def open_index(home, name="hash-test"):
    return Index(home, HashEmbedder(name=name))


def test_sync_indexes_markdown_and_raw(tmp_path):
    home = make_home(tmp_path)
    stats = open_index(home).sync()
    assert stats.indexed == 3 and stats.removed == 0


def test_exact_identifier_found(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    hits = search(idx, "ENG-402")
    assert hits[0].path == "sources/mailtest/t1.json"


def test_unchanged_files_are_skipped(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    assert idx.sync().indexed == 0


def test_changed_file_replaces_old_chunks(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    atomic_write(home / "people/alex_rivera.md", "---\nname: Alex Rivera\n---\n## Notes\nNow owns kafka.\n")
    assert idx.sync().indexed == 1
    assert search(idx, "Redis") == [] or all(h.path != "people/alex_rivera.md" for h in search(idx, "Redis"))
    assert search(idx, "kafka")[0].path == "people/alex_rivera.md"


def test_deleted_file_is_removed(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    (home / "sources/mailtest/t2.json").unlink()
    assert idx.sync().removed == 1
    assert all(h.path != "sources/mailtest/t2.json" for h in search(idx, "Tacos"))


def test_filters_by_source_and_time(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    assert {h.source for h in search(idx, "Redis review patch", source="people")} == {"people"}
    assert all(h.ts >= "2026-09-15" for h in search(idx, "review tacos", source="mailtest", since="2026-09-15"))


def test_rebuild_from_files_gives_same_results(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    before = [(h.path, h.chunk_id) for h in search(idx, "review the patch")]
    idx.close()
    home.db.unlink()
    idx2 = open_index(home)
    idx2.sync()
    assert [(h.path, h.chunk_id) for h in search(idx2, "review the patch")] == before


def test_embedder_change_triggers_full_rebuild(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home, name="model-a")
    idx.sync()
    idx.close()
    idx = open_index(home, name="model-b")
    assert idx.sync().indexed == 3


def test_config_and_logs_are_not_indexed(tmp_path):
    home = make_home(tmp_path)
    atomic_write(home / "logs/x.md", "# secretlog\n")
    idx = open_index(home)
    idx.sync()
    assert search(idx, "secretlog") == []


def test_rrf_rewards_agreement():
    merged = rrf([["a", "b", "c"], ["c", "a"]], k=60)
    assert merged[0] == "a"
    assert set(merged) == {"a", "b", "c"}


def test_chunk_text_is_retrievable(tmp_path):
    home = make_home(tmp_path)
    idx = open_index(home)
    idx.sync()
    assert "review the patch" in idx.chunk_text("sources/mailtest/t1.json", "c0")
