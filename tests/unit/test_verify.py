from archie.llm.verify import Packet, verify_claims

CHUNK = "Hi Test, can you review the Redis fallback patch before Friday?  Thanks, Sarah"


def packet() -> Packet:
    p = Packet()
    p.add("sources/gmail/t1.json", "c0", CHUNK, label="Email from Sarah, Oct 1")
    p.add("people/alex.md", "c1", "Alex owns the auth token pipeline.", label="Alex's dossier")
    return p


def claim(text, *cites):
    return {"text": text, "citations": [{"ref": r, "quote": q} for r, q in cites]}


def test_verbatim_quote_passes_and_resolves_to_file():
    out = verify_claims([claim("Sarah wants a review by Friday", (1, "review the Redis fallback patch before Friday"))], packet())
    assert len(out.kept) == 1
    assert out.kept[0].citations[0].path == "sources/gmail/t1.json"
    assert out.kept[0].citations[0].chunk_id == "c0"


def test_fabricated_quote_is_dropped():
    out = verify_claims([claim("Sarah is angry", (1, "Sarah is furious about the delay"))], packet())
    assert out.kept == [] and len(out.dropped) == 1


def test_quote_from_wrong_chunk_is_dropped():
    out = verify_claims([claim("x", (2, "review the Redis fallback patch"))], packet())
    assert out.kept == []


def test_unknown_ref_is_dropped():
    out = verify_claims([claim("x", (9, "review the Redis fallback patch"))], packet())
    assert out.kept == []


def test_claim_without_citations_is_dropped():
    out = verify_claims([{"text": "Alex is great", "citations": []}], packet())
    assert out.kept == []


def test_whitespace_case_and_curly_quotes_are_normalized():
    p = Packet()
    p.add("f.md", "c0", "Alex said “ship it”   today.\nOK")
    out = verify_claims([claim("x", (1, 'alex said "ship it" today.'))], p)
    assert len(out.kept) == 1


def test_trivially_short_quote_is_rejected():
    out = verify_claims([claim("x", (1, "the"))], packet())
    assert out.kept == []


def test_one_bad_citation_does_not_sink_a_good_one():
    out = verify_claims([claim("x", (1, "made up words here"), (2, "owns the auth token pipeline"))], packet())
    assert len(out.kept) == 1 and len(out.kept[0].citations) == 1


def test_packet_renders_numbered_items_for_the_prompt():
    text = packet().render()
    assert text.startswith('<source n="1">\n[1] Email from Sarah, Oct 1')
    assert "[2] Alex's dossier" in text


def test_hollow_quotes_support_nothing():
    from archie.llm.verify import Packet, check_quote

    p = Packet()
    p.add("a.json", "c0", "From Workperson Acorn <workperson@x.io> to Test\nSubject: Re: Onboarding\n\nHi Ms. Workpersonfour & Maestra,\n"
                          "Welcome aboard! I run people ops at Overwatch.")
    assert check_quote(p, 1, "Workperson Acorn <workperson@x.io>") is None
    assert check_quote(p, 1, "Hi Ms. Workpersonfour & Maestra,") is None
    assert check_quote(p, 1, "Re: Onboarding") is None
    assert check_quote(p, 1, "I run people ops at Overwatch") is not None


def test_the_model_reads_a_tidy_excerpt_but_quotes_are_checked_against_the_original():
    from archie.llm.verify import Packet, check_quote, tidy

    raw = ("---\nevent_id: x\n---\nFrom Pool <p@x.io> to Test, 2026-10-01T04:47\nSubject: Swim\n\n"
           "Lessons move to Tuesday. ![](https://img.example/a.png) [image: map.png]\n"
           "Track: https://t.example/" + "a" * 80 + "\nTo unsubscribe click here\n\n\n\nThanks")
    shown = tidy(raw)
    assert "event_id" not in shown and "unsubscribe" not in shown and "aaaa" not in shown
    assert "2026-10-01T04:47" not in shown and "(image)" in shown and "Lessons move to Tuesday." in shown
    p = Packet()
    p.add("a.json", "c0", raw)
    assert check_quote(p, 1, "Lessons move to Tuesday.") is not None
    assert check_quote(p, 1, "Track: <link>") is None  # only words really in the source verify
