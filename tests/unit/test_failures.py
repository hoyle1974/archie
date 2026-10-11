from datetime import datetime, timezone

from archie import doctor
from archie.derive.failures import MAX_TRIES, Failures
from archie.derive.loops import derive_loops
from archie.llm.backend import FakeBackend, LLMError
from archie.store.home import init_home
from tests.support.fixtures import by_schema, make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"
ASK = msg("m1", "sarah.t@acme.example", "Sarah Jones", [addr(TEST, "Test")], "2026-09-28T16:30:00+00:00",
          "Hi Test, can you review the Redis fallback patch before Friday?", subject="Redis fallback", to_me=True)
LATER = msg("m2", "sarah.t@acme.example", "Sarah Jones", [addr(TEST, "Test")], "2026-09-30T09:00:00+00:00",
            "Any update on the patch?", subject="Re: Redis fallback", to_me=True)
UNREADABLE = LLMError("the model's reply couldn't be read (missing `x`)", about_input=True)


def test_only_failures_caused_by_the_input_count(tmp_path):
    f = Failures(init_home(tmp_path / "h"))
    for _ in range(5):
        f.failed("gmail:t1", "v1", LLMError("Gemini's rate or quota limit is reached"))
    assert not f.gave_up("gmail:t1", "v1")
    for _ in range(MAX_TRIES):
        f.failed("gmail:t1", "v1", UNREADABLE)
    assert f.gave_up("gmail:t1", "v1")
    assert not f.gave_up("gmail:t1", "v2")  # new content gets a fresh start


def test_success_clears_and_the_record_is_a_file(tmp_path):
    home = init_home(tmp_path / "h")
    f = Failures(home)
    for _ in range(MAX_TRIES):
        f.failed("gmail:t1", "v1", UNREADABLE)
        f.failed("people:sam", "v1", UNREADABLE)
    f.ok("people:sam")
    f.save()
    again = Failures(home)
    assert again.gave_up("gmail:t1", "v1") and not again.gave_up("people:sam", "v1")
    assert again.skipped() == ["gmail:t1"]


def test_a_thread_that_keeps_failing_stops_costing_calls(tmp_path):
    fb = FakeBackend(by_schema(loops_extract="LOOP asked_of_me\nsummary: Review the patch"))  # no cite
    ctx = make_ctx(tmp_path, fb, now=datetime(2026, 10, 1, 16, tzinfo=timezone.utc))
    path = write_thread(ctx.home, "t1", [ASK])
    for _ in range(MAX_TRIES + 2):
        derive_loops(ctx, [path])
    assert len(fb.calls) == MAX_TRIES
    write_thread(ctx.home, "t1", [ASK, LATER])  # a new message changes the input: try again
    derive_loops(ctx, [path])
    assert len(fb.calls) == MAX_TRIES + 1


def test_service_outage_never_makes_a_thread_give_up(tmp_path):
    def down(system, user, shape, tier):
        raise LLMError("couldn't reach Gemini; check the network connection")

    fb = FakeBackend(by_schema(loops_extract=down))
    ctx = make_ctx(tmp_path, fb, now=datetime(2026, 10, 1, 16, tzinfo=timezone.utc))
    path = write_thread(ctx.home, "t1", [ASK])
    for _ in range(MAX_TRIES + 2):
        derive_loops(ctx, [path])
    assert len(fb.calls) == MAX_TRIES + 2


def test_doctor_reports_skipped_items(tmp_path):
    home = init_home(tmp_path / "h")
    assert doctor.check_failures(home) is None
    f = Failures(home)
    for _ in range(MAX_TRIES):
        f.failed("gmail:t1", "v1", UNREADABLE)
    f.save()
    ok, message = doctor.check_failures(home)
    assert not ok and "1 item" in message and "llm_failures.yaml" in message
