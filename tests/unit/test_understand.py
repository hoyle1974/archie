from archie.ask.understand import Part, checked, prompt_input, understand
from archie.llm.backend import FakeBackend
from tests.support.fixtures import make_ctx

RECENT = [{"ts": "2026-10-01T16:00:00+00:00", "said": "did HeadphonesRUs reply about my earbud?", "resolved": None,
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


PENDING = {"kind": "loops", "action": "done", "options": [{"label": "Workpersonthree's pizza instructions", "id": "l1"},
                                                          {"label": "Workpersonfour's IEP form", "id": "l2"}]}


def test_an_answer_to_which_one_must_pick_one_listed_option():
    said = "the school one"
    [p] = checked([{"kind": "answer", "text": said, "options": [2]}], said, [], [], PENDING)
    assert (p.kind, p.options, p.question) == ("answer", [2], None)
    for bad, pending in (([3], PENDING), ([1, 2], PENDING), ([2], None)):
        [p] = checked([{"kind": "answer", "text": said, "options": bad}], said, [], [], pending)
        assert (p.kind, p.options) == ("question", []), (bad, pending)


def test_unclear_options_must_be_open_questions():
    said = "it's my plumber"
    [p] = checked([{"kind": "unclear", "text": said, "options": [1, 1, 4]}], said, [], WHO)
    assert p.options == [1]


def test_the_pending_question_is_shown_to_the_model():
    text = prompt_input("the school one", [], [], PENDING)
    assert ("Archie just asked: Which one: Workpersonthree's pizza instructions or Workpersonfour's IEP form?\n"
            "1. Workpersonthree's pizza instructions\n2. Workpersonfour's IEP form\n") in text


def test_no_parts_means_search_the_whole_message():
    assert checked([], "zebras?", [], []) == [Part(kind="question", text="zebras?", intent="search",
                                                   params={"people": [], "since": None, "until": None,
                                                           "topic": None, "meeting": None, "text": None,
                                                           "mine": False})]


def test_the_model_sees_the_conversation_and_open_questions_and_the_message_last():
    text = prompt_input("do you see the message I sent them?", RECENT, WHO)
    assert "You: did HeadphonesRUs reply about my earbud?" in text
    assert "Archie: HeadphonesRUs offered a replacement right earbud. [1]" in text
    assert "Sources: [1] HeadphonesRUs (dossier)" in text
    assert "1. Who is a@b.co?" in text
    assert text.endswith("Message: do you see the message I sent them?")
    assert "Recent conversation" not in prompt_input("hi", [], [])


def test_names_must_be_whole_words_someone_said():
    recent = [{**RECENT[0], "summary": "See you tomorrow; the token expired."}]
    q = {"kind": "question", "text": "did he reply?", "intent": "search",
         "resolved": "Did Tom reply to Ken about the budget?"}
    assert checked([q], q["text"], recent, [])[0].resolved is None


def test_people_nobody_mentioned_are_dropped():
    q = {"kind": "question", "text": "who is she?", "intent": "who", "people": ["Bose", "HeadphonesRUs"]}
    assert checked([q], q["text"], RECENT, [])[0].params["people"] == ["HeadphonesRUs"]
    q = {"kind": "question", "text": "who is priya?", "intent": "who", "people": ["Priya Sharma"]}
    assert checked([q], q["text"], [], [])[0].params["people"] == ["Priya Sharma"]


def test_an_ask_back_naming_someone_nobody_mentioned_is_dropped():
    [p] = checked([{"kind": "unclear", "text": "she's done", "ask": "Do you mean your sister Goodspouse?"}],
                  "she's done", [], [])
    assert p.ask is None


def test_the_model_sees_what_earlier_messages_were_understood_as():
    entry = {**RECENT[0], "said": "really?", "resolved": "Did HeadphonesRUs reply about my earbud?"}
    assert "You: really? (meaning: Did HeadphonesRUs reply about my earbud?)" in prompt_input("and then?", [entry], [])


def test_about_must_be_someone_or_something_said():
    [p] = checked([{"kind": "tell", "text": "ignore it", "fact": "ignore", "about": "Ken Smith"}], "ignore it", [], [])
    assert p.about is None
    [p] = checked([{"kind": "tell", "text": "ignore Goodcompany", "fact": "ignore", "about": "Goodcompany"}],
                  "ignore Goodcompany", [], [])
    assert p.about == "Goodcompany"


def test_mine_is_read_as_a_yes_or_no():
    [p] = checked([{"kind": "question", "text": "did they get what I sent?", "intent": "search", "mine": True}],
                  "did they get what I sent?", [], [])
    assert p.params["mine"] is True
    [p] = checked([{"kind": "question", "text": "zebras?", "intent": "search", "mine": None}], "zebras?", [], [])
    assert p.params["mine"] is False


def test_possessive_names_stay_grounded():
    raw = [{"kind": "question", "text": "x", "intent": "who", "people": ["Workperson"], "topic": "title"}]
    for message in ("What is Workpersons title?", "What is Workperson's title?", "What is Workperson’s title?"):
        [p] = checked(raw, message, [], [])
        assert p.params["people"] == ["Workperson"], message


def test_names_nobody_said_are_still_dropped():
    raw = [{"kind": "question", "text": "x", "intent": "who", "people": ["Bose"]}]
    [p] = checked(raw, "What is Workpersons title?", [], [])
    assert p.params["people"] == []
