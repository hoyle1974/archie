from archie.index.chunk import Chunk, chunk_markdown, chunk_windows, register_raw_chunker, chunk_file


def test_offsets_point_back_into_the_text():
    text = "---\ntype: Person\n---\n# A\nalpha text\n## B\nbeta text\n"
    for c in chunk_markdown("p.md", text):
        assert text[c.char_start : c.char_end] == c.text


def test_markdown_splits_at_headings():
    text = "# One\nfirst\n# Two\nsecond\n"
    chunks = chunk_markdown("n.md", text)
    assert [c.text.splitlines()[0] for c in chunks] == ["# One", "# Two"]
    assert [c.chunk_id for c in chunks] == ["c0", "c1"]


def test_frontmatter_is_its_own_chunk():
    chunks = chunk_markdown("p.md", "---\nname: Alex\n---\nbody\n")
    assert "name: Alex" in chunks[0].text
    assert chunks[1].text.strip() == "body"


def test_long_section_is_windowed_with_overlap():
    words = [f"w{i}" for i in range(700)]
    text = "# Big\n" + " ".join(words) + "\n"
    chunks = chunk_markdown("big.md", text, max_words=300, overlap_words=50)
    assert len(chunks) == 3
    assert "w250" in chunks[0].text and "w250" in chunks[1].text  # overlap
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text
        assert len(c.text.split()) <= 300


def test_blank_sections_are_dropped():
    assert chunk_markdown("e.md", "\n\n") == []


def test_windows_on_short_text_is_one_chunk():
    assert len(chunk_windows("x.txt", "a b c", base=10)) == 1
    assert chunk_windows("x.txt", "a b c", base=10)[0].char_start == 10


def test_chunk_file_dispatches_raw_json_by_source(tmp_path):
    def fake(path, data):
        return [Chunk("c0", path, 0, 0, data["subject"], source="fake", ts="2026-10-01T00:00:00Z")]

    register_raw_chunker("fake", fake)
    chunks = chunk_file("sources/fake/1.json", '{"subject": "hello"}')
    assert chunks[0].text == "hello" and chunks[0].source == "fake"


def test_chunk_file_skips_tombstones_and_unknown_sources():
    assert chunk_file("sources/fake/1.json", '{"deleted": true}') == []
    assert chunk_file("sources/nobody/1.json", '{"x": 1}') == []


def test_markdown_chunks_get_readable_labels():
    c = chunk_file("people/priya_sharma.md", "---\nname: Priya Sharma\n---\nhi\n")
    assert c[0].label == "Priya Sharma (dossier)"
    m = chunk_file("meetings/2026/x.md", "---\ntitle: Design review\nstart: 2026-09-28T21:00:00Z\n---\nhi\n")
    assert m[0].label == "Design review (meeting notes, Sep 28)"


def test_label_falls_back_to_file_name():
    assert chunk_file("people/alex_rivera.md", "hi\n")[0].label == "alex rivera (dossier)"
