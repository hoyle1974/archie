from datetime import datetime, timezone

from archie.derive.loops import derive_loops, load_loops, rank, save_loop
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"
ASK = msg("m1", "sarah.j@acme.example", "Sarah Jones", [addr(TEST, "Test")], "2026-09-28T16:30:00+00:00",
          "Hi Test, can you review the Redis fallback patch before Friday? Thanks", subject="Redis fallback", to_me=True)
REPLY = msg("m2", TEST, "Test", [addr("sarah.j@acme.example", "Sarah Jones")], "2026-09-29T17:00:00+00:00",
            "Reviewed it, looks good. Approved the patch.", subject="Re: Redis fallback", from_me=True)
PROMISE = msg("m3", TEST, "Test", [addr("ken@acme.example", "Ken Ito")], "2026-09-26T17:00:00+00:00",
              "I'll send you the Q4 capacity numbers by Monday.", subject="Capacity", from_me=True)


def extraction(*loops):
    return {"loops": list(loops)}


def cand(kind, ref, quote, summary, due=None):
    return {"kind": kind, "ref": ref, "quote": quote, "summary": summary, "due": due,
            "resolved": False, "resolved_ref": None, "resolved_quote": None}


def ctx_with(tmp_path, **handlers):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(**handlers)), now=datetime(2026, 10, 1, 16, tzinfo=timezone.utc))
    return ctx


def test_inbound_request_becomes_open_asked_of_me_loop(tmp_path):
    ctx = ctx_with(tmp_path, loops_extract=extraction(
        cand("asked_of_me", 1, "can you review the Redis fallback patch before Friday", "Review the Redis fallback patch",
             "2026-12-25")))  # the model's date is ignored: code reads "before Friday" from the quote
    path = write_thread(ctx.home, "t1", [ASK])
    derive_people(ctx, [path])
    derive_loops(ctx, [path])
    [loop] = load_loops(ctx.home)
    assert loop.meta["kind"] == "asked_of_me" and loop.meta["status"] == "open"
    assert loop.meta["counterpart"] == "sarah_jones"
    assert loop.meta["due"] == "2026-10-02"
    assert loop.meta["sources"][0]["file"] == "sources/gmail/t1.json"
    assert loop.meta["sources"][0]["chunk"] == "c0"


def test_fabricated_quote_creates_no_loop(tmp_path):
    ctx = ctx_with(tmp_path, loops_extract=extraction(cand("asked_of_me", 1, "please buy me a pony", "Buy a pony")))
    derive_loops(ctx, [write_thread(ctx.home, "t1", [ASK])])
    assert load_loops(ctx.home) == []


def test_direction_must_match_kind(tmp_path):
    # asked_of_me citing the user's own message is rejected
    ctx = ctx_with(tmp_path, loops_extract=extraction(cand("asked_of_me", 1, "send you the Q4 capacity numbers", "x")))
    derive_loops(ctx, [write_thread(ctx.home, "t3", [PROMISE])])
    assert load_loops(ctx.home) == []


def test_promise_counterpart_is_the_recipient(tmp_path):
    ctx = ctx_with(tmp_path, loops_extract=extraction(
        cand("i_promised", 1, "send you the Q4 capacity numbers by Monday", "Send Ken the Q4 capacity numbers")))
    derive_loops(ctx, [write_thread(ctx.home, "t3", [PROMISE])])
    [loop] = load_loops(ctx.home)
    assert loop.meta["kind"] == "i_promised" and loop.meta["counterpart"] == "ken@acme.example"


def test_reply_in_thread_closes_loop_with_evidence(tmp_path):
    ctx = ctx_with(tmp_path,
                   loops_extract=extraction(cand("asked_of_me", 1, "can you review the Redis fallback patch",
                                                 "Review the Redis fallback patch")),
                   loops_close={"updates": [{"loop": 1, "resolved": True, "ref": 2,
                                             "quote": "Approved the patch"}]})
    p = write_thread(ctx.home, "t1", [ASK])
    derive_loops(ctx, [p])
    p = write_thread(ctx.home, "t1", [ASK, REPLY])
    derive_loops(ctx, [p])
    [loop] = load_loops(ctx.home)
    assert loop.meta["status"] == "done"
    assert loop.meta["closed_by"]["quote"] == "Approved the patch"
    assert loop.meta["closed_by"]["chunk"] == "c1"


def test_unverified_closure_keeps_loop_open(tmp_path):
    ctx = ctx_with(tmp_path,
                   loops_extract=extraction(cand("asked_of_me", 1, "can you review the Redis fallback patch", "Review")),
                   loops_close={"updates": [{"loop": 1, "resolved": True, "ref": 2, "quote": "I merged it to main"}]})
    derive_loops(ctx, [write_thread(ctx.home, "t1", [ASK])])
    derive_loops(ctx, [write_thread(ctx.home, "t1", [ASK, REPLY])])
    assert load_loops(ctx.home)[0].meta["status"] == "open"


def test_already_processed_messages_are_not_reextracted(tmp_path):
    fb_calls = []

    def ext(system, user, schema, tier):
        fb_calls.append(user)
        return extraction()

    ctx = ctx_with(tmp_path, loops_extract=ext, loops_close={"updates": []})
    p = write_thread(ctx.home, "t1", [ASK])
    derive_loops(ctx, [p])
    derive_loops(ctx, [p])
    assert len(fb_calls) == 1


def test_bulk_only_threads_never_reach_the_llm(tmp_path):
    ctx = ctx_with(tmp_path)  # no handlers: any LLM call would raise
    news = msg("m9", "news@x.example", "News", [addr(TEST)], "2026-09-30T00:00:00+00:00", "Sale", to_me=True, bulk=True)
    derive_loops(ctx, [write_thread(ctx.home, "t9", [news])])
    assert load_loops(ctx.home) == []


def test_user_edits_outside_fence_survive_and_status_is_respected(tmp_path):
    ctx = ctx_with(tmp_path, loops_extract=extraction(
        cand("asked_of_me", 1, "can you review the Redis fallback patch", "Review")),
                   loops_close={"updates": [{"loop": 1, "resolved": True, "ref": 2, "quote": "Approved the patch"}]})
    derive_loops(ctx, [write_thread(ctx.home, "t1", [ASK])])
    [loop] = load_loops(ctx.home)
    loop.meta["status"] = "dismissed"
    loop.note.body = "My note: not needed.\n" + loop.note.body
    save_loop(ctx.home, loop)
    derive_loops(ctx, [write_thread(ctx.home, "t1", [ASK, REPLY])])
    [again] = load_loops(ctx.home)
    assert again.meta["status"] == "dismissed" and "My note: not needed." in again.note.body


def test_rank_puts_due_soon_and_asked_of_me_first(tmp_path):
    ctx = ctx_with(tmp_path)
    from archie.derive.loops import Loop
    from archie.store.files import Note

    def mk(i, kind, created, due=None):
        return Loop(f"l{i}", f"loops/2026/l{i}.md", Note(meta={"loop_id": f"l{i}", "kind": kind, "status": "open",
                                                               "created_at": created, "due": due, "summary": f"s{i}"}))

    loops = [mk(1, "waiting_on", "2026-09-20T00:00:00+00:00"),
             mk(2, "asked_of_me", "2026-09-30T00:00:00+00:00", due="2026-10-02"),
             mk(3, "i_promised", "2026-09-26T00:00:00+00:00")]
    ranked = rank(loops, ctx.now, ctx.config)
    assert [r.loop.loop_id for r in ranked][0] == "l2"
    assert any("due" in why for why in ranked[0].why)


def test_llm_failure_leaves_thread_for_retry(tmp_path):
    ctx = ctx_with(tmp_path)  # FakeBackend with no handler for loops_extract -> KeyError... use LLMError
    from archie.llm.backend import FakeBackend

    ctx.backend = FakeBackend([])  # raises LLMError
    p = write_thread(ctx.home, "t1", [ASK])
    derive_loops(ctx, [p])
    ctx.backend = FakeBackend(by_schema(loops_extract=extraction(
        cand("asked_of_me", 1, "can you review the Redis fallback patch", "Review"))))
    derive_loops(ctx, [p])
    assert len(load_loops(ctx.home)) == 1


def test_same_request_quoted_differently_is_not_duplicated(tmp_path):
    first = cand("asked_of_me", 1, "can you review the Redis fallback patch before Friday", "Review the patch")
    again = cand("asked_of_me", 1, "review the Redis fallback patch before Friday? Thanks", "Review Redis patch")
    ctx = ctx_with(tmp_path, loops_extract=extraction(first))
    p = write_thread(ctx.home, "t1", [ASK])
    derive_loops(ctx, [p])
    (ctx.home / "state/loops_seen.yaml").unlink()  # simulate a re-run over the same mail
    ctx.backend = FakeBackend(by_schema(loops_extract=extraction(again), loops_close={"updates": []}))
    derive_loops(ctx, [p])
    assert len(load_loops(ctx.home)) == 1


def test_long_overdue_items_are_flagged_stale_not_urgent(tmp_path):
    ctx = ctx_with(tmp_path)
    from archie.derive.loops import Loop
    from archie.store.files import Note

    def mk(i, due, created):
        return Loop(f"l{i}", f"loops/2026/l{i}.md", Note(meta={"loop_id": f"l{i}", "kind": "asked_of_me",
                                                               "status": "open", "created_at": created, "due": due,
                                                               "summary": f"s{i}"}))

    ranked = rank([mk(1, "2026-09-20", "2026-09-15T00:00:00+00:00"), mk(2, "2026-10-02", "2026-09-30T00:00:00+00:00")],
                  ctx.now, ctx.config)
    assert [r.loop.loop_id for r in ranked] == ["l2", "l1"]
    assert ranked[1].stale and "still needed?" in ranked[1].why[0]


def test_first_contacts_are_marked_for_the_model(tmp_path):
    seen = []  # threads are processed in parallel, so keep every prompt

    def ext(system, user, shape, tier):
        seen.append(user)
        return extraction()

    ctx = ctx_with(tmp_path, loops_extract=ext)
    cold = msg("c1", "recruiter@x.example", "Rita Recruiter", [addr(TEST)], "2026-09-30T00:00:00+00:00",
               "Reply if you're interested!", to_me=True)
    derive_loops(ctx, [write_thread(ctx.home, "t2", [PROMISE]), write_thread(ctx.home, "t8", [cold])])
    assert any("first contact" in u and "Rita Recruiter" in u for u in seen)
    seen.clear()
    ken = msg("k2", "ken@acme.example", "Ken Ito", [addr(TEST)], "2026-09-30T00:00:00+00:00", "Thanks!", to_me=True)
    derive_loops(ctx, [write_thread(ctx.home, "t9", [ken])])
    assert not any("first contact" in u for u in seen)  # the user has written to Ken before


def test_derive_loops_records_the_version_per_thread(tmp_path):
    import yaml

    from archie.derive.loops import loop_version

    ctx = ctx_with(tmp_path, loops_extract=extraction())
    path = write_thread(ctx.home, "t1", [ASK])
    derive_people(ctx, [path])
    derive_loops(ctx, [path])
    seen = yaml.safe_load((ctx.home / "state/loops_seen.yaml").read_text())
    assert seen["_versions"]["t1"] == loop_version()
    assert seen["t1"] == ASK["date"]
