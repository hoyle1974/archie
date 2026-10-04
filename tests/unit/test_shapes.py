import pytest

from archie.ask.intents.clarify import SHAPE as CLARIFY
from archie.ask.intents.correct import SHAPE as CORRECT
from archie.ask.intents.loops import UPDATE_SHAPE as UPDATE
from archie.ask.intents.notes import SHAPE as NOTES
from archie.ask.intents.remember import SHAPE as REMEMBER
from archie.ask.synthesize import SHAPE as ANSWER
from archie.ask.understand import SHAPE as UNDERSTAND
from archie.derive.cross_close import SHAPE as CROSS
from archie.derive.enrich import SHAPE as FACTS
from archie.derive.loops import CLOSE_SHAPE as CLOSE
from archie.derive.loops import EXTRACT_SHAPE as EXTRACT

ALL = [UNDERSTAND, ANSWER, CLARIFY, CORRECT, UPDATE, NOTES, REMEMBER, EXTRACT, CLOSE, CROSS, FACTS]


def test_eleven_shapes_named_like_the_old_schemas():
    assert sorted(s.name for s in ALL) == sorted(["understand", "answer", "clarify", "correct", "loop_update",
                                                  "notes_actions", "remember", "loops_extract", "loops_close",
                                                  "loops_cross", "people_facts"])


@pytest.mark.parametrize("shape", [s for s in ALL if not s.claims], ids=lambda s: s.name)
def test_each_example_parses_cleanly(shape):
    out, problems = shape.parse(shape.example)
    assert problems == [] and out


def test_understand():
    out, problems = UNDERSTAND.parse("PART question\ntext: who is Ken?\nintent: who\npeople: Ken\n"
                                     "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam")
    assert problems == []
    assert [(p["kind"], p["text"], p["intent"], p["people"], p["fact"]) for p in out["parts"]] == [
        ("question", "who is Ken?", "who", ["Ken"], None), ("tell", "Sam is my neighbor.", None, [], "person")]


def test_clarify():
    assert CLARIFY.parse("ANSWER 2\nsame: yes\nANSWER 1\nsame: no") == (
        {"answers": [{"question": 2, "same": True}, {"question": 1, "same": False}]}, [])


def test_correct():
    out, problems = CORRECT.parse("kind: same_person\nalias: Al R.\nperson: Alex Rivera")
    assert problems == []
    assert out == {"kind": "same_person", "meeting": None, "meeting_type": None, "alias": "Al R.",
                   "person": "Alex Rivera", "role": None}


def test_loop_update():
    assert UPDATE.parse("action: snooze\nloops: 2; 3\nuntil: 2026-10-05\nreason: -") == (
        {"action": "snooze", "loops": [2, 3], "until": "2026-10-05", "reason": None}, [])
    assert UPDATE.parse("action: done\nloops: -")[0]["loops"] == []


def test_notes_actions():
    out, problems = NOTES.parse("ITEM me\ntext: Update the runbook\nquote: I need to update the runbook by next Wed\n"
                                "ITEM Alex\ntext: Add a circuit breaker\nquote: Alex to add circuit breaker")
    assert problems == []
    assert out["items"][0] == {"owner": "me", "text": "Update the runbook",
                               "quote": "I need to update the runbook by next Wed"}
    assert out["items"][1]["owner"] == "Alex"


def test_remember():
    out, problems = REMEMBER.parse("PERSON Goodspouse\nrelationship: wife\nrole: -\npronouns: she/her\nidentity: -\n"
                                   "avoid: -\nother_names: Belle; Goodspouse Mae Testerson\nstatement: Goodspouse is my wife.")
    assert problems == []
    assert out == {"people": [{"name": "Goodspouse", "relationship": "wife", "role": None, "pronouns": "she/her",
                               "identity": None, "avoid": [], "other_names": ["Belle", "Goodspouse Mae Testerson"],
                               "statement": "Goodspouse is my wife."}]}


def test_loops_extract_and_close():
    out, problems = EXTRACT.parse('LOOP asked_of_me\nsummary: Review the patch\n'
                                  'cite: [3] "can you review the patch before Friday"\nresolved: no')
    assert problems == []
    assert out["loops"] == [{"kind": "asked_of_me", "summary": "Review the patch", "ref": 3,
                             "quote": "can you review the patch before Friday", "resolved": False}]
    out, problems = CLOSE.parse('UPDATE 1\nresolved: yes\ncite: [4] "I merged the fix this morning"\n'
                                'UPDATE 2\nresolved: no\ncite: -')
    assert problems == []
    assert out["updates"] == [{"loop": 1, "resolved": True, "ref": 4, "quote": "I merged the fix this morning"},
                              {"loop": 2, "resolved": False}]


def test_loops_cross():
    assert CROSS.parse("done: no\nstrength: -\ncite: -") == ({"done": False, "strength": None}, [])
    out, _ = CROSS.parse('done: yes\nstrength: weak\ncite: [2] "Approved the fallback patch"')
    assert out == {"done": True, "strength": "weak", "ref": 2, "quote": "Approved the fallback patch"}


def test_people_facts():
    out, problems = FACTS.parse('FACT Product manager for auth\ncite: [2] "I\'m the PM for auth"\nNONE')
    assert problems == []
    assert out == {"facts": [{"text": "Product manager for auth", "ref": 2, "quote": "I'm the PM for auth"}]}


def test_answer_is_claims():
    assert ANSWER.claims and ANSWER.name == "answer"
