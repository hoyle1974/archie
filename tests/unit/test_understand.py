from archie.ask.understand import Part, checked, prompt_input, understand
from archie.llm.backend import FakeBackend
from tests.support.fixtures import make_ctx

RECENT = [{"ts": "2026-10-01T16:00:00+00:00", "said": "did Status reply about my earbud?", "resolved": None,
           "summary": "HeadphonesRUs offered a replacement right earbud. [1]",
           "citations": [{"n": 1, "file": "people/status_audio.md", "chunk": "c0", "label": "HeadphonesRUs (dossier)",
                          "quote": "offering a replacement right earbud"}]}]
WHO = [{"id": "q1", "kind": "who_is", "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
        "status": "open"}]


def test_text_reply_becomes_parts(tmp_path):
    reply = ("PART instruct\ntext: I picked up the pizza.\naction: loop_done\n"
             "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam")
    ctx = make_ctx(tmp_path, FakeBackend([reply]))
    parts = understand(ctx, "I picked up the pizza. Sam is my neighbor.", [], [])
    assert [(p.kind, p.text, p.action, p.fact) for p in parts] == [
        ("instruct", "I picked up the pizza.", "loop_done", None), ("tell", "Sam is my neighbor.", None, "person")]
    assert ctx.backend.calls[0]["shape"].name == "understand" and ctx.backend.calls[0]["tier"] == "fast"


def test_one_part_always_carries_the_whole_message():
    message = "notes from the design review:\nRedis approved.\nI need to update the runbook."
    [p] = checked([{"kind": "instruct", "text": "notes from the design review:", "action": "notes"}], message, [], [])
    assert p.text == message


def test_part_words_not_in_the_message_fall_back_to_the_message():
    message = "I left.  Sam is my neighbor."
    parts = checked([{"kind": "instruct", "text": "invented words", "action": "loop_done"},
                     {"kind": "tell", "text": "Sam is my neighbor.", "fact": "person"}], message, [], [])
    assert [p.text for p in parts] == [message, "Sam is my neighbor."]


def test_resolved_may_only_use_names_someone_said():
    ok = {"kind": "question", "text": "do you see the message I sent them?", "intent": "search",
          "resolved": "Do you see the message I sent HeadphonesRUs about the earbud?"}
    made_up = {**ok, "resolved": "Do you see the message I sent Bose about the earbud?"}
    assert checked([ok], ok["text"], RECENT, [])[0].resolved == ok["resolved"]
    assert checked([made_up], ok["text"], RECENT, [])[0].resolved is None
    assert checked([ok], ok["text"], [], [])[0].resolved is None  # nothing recent said "HeadphonesRUs"


def test_answer_to_a_question_that_does_not_exist_becomes_a_question():
    [p] = checked([{"kind": "answer", "text": "it's my plumber", "question": 4}], "it's my plumber", [], WHO)
    assert (p.kind, p.question) == ("question", None)
    [p] = checked([{"kind": "answer", "text": "it's my plumber", "question": 1}], "it's my plumber", [], WHO)
    assert (p.kind, p.question) == ("answer", 1)


def test_no_parts_means_search_the_whole_message():
    assert checked([], "zebras?", [], []) == [Part(kind="question", text="zebras?", intent="search",
                                                   params={"people": [], "since": None, "until": None,
                                                           "topic": None, "meeting": None, "text": None})]


def test_the_model_sees_the_conversation_and_open_questions_and_the_message_last():
    text = prompt_input("do you see the message I sent them?", RECENT, WHO)
    assert "You: did Status reply about my earbud?" in text
    assert "Archie: HeadphonesRUs offered a replacement right earbud. [1]" in text
    assert "Sources: [1] HeadphonesRUs (dossier)" in text
    assert "1. Who is a@b.co?" in text
    assert text.endswith("Message: do you see the message I sent them?")
    assert "Recent conversation" not in prompt_input("hi", [], [])
