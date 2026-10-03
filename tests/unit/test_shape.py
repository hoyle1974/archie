from archie.llm.shape import F, Record, Shape

ROUTE = Shape(
    "route",
    fields=(F("intent", "choice", choices=("search", "remember", "loop_update")),
            F("people", "list", required=False), F("since", required=False), F("text", required=False)),
    records=(Record("ALSO", "also", F("intent", "choice", choices=("remember", "loop_update")), (F("text"),)),),
    nest=("params", ("people", "since", "text")),
    example="intent: search\npeople: -\nsince: -\ntext: -",
)
LOOPS = Shape("loops_extract", records=(Record("LOOP", "loops", F("kind", "choice", choices=("asked_of_me", "waiting_on")), (
    F("summary"), F("cite", "cite", keys=("ref", "quote")), F("resolved", "bool", required=False),
    F("resolved_cite", "cite", required=False, keys=("resolved_ref", "resolved_quote")))),))


def test_fields_lists_nulls_and_nesting():
    out, problems = ROUTE.parse("intent: search\npeople: Alex Rivera; priya@x.example\nsince: -\ntext: none")
    assert problems == []
    assert out == {"intent": "search", "also": [],
                   "params": {"people": ["Alex Rivera", "priya@x.example"], "since": None, "text": None}}


def test_forgiving_about_fences_chatter_bullets_bold_and_key_case():
    reply = "Sure! Here you go:\n```\n- **Intent:** remember\n* People: Goodspouse\n```\nHope that helps."
    out, problems = ROUTE.parse(reply)
    assert problems == []
    assert out["intent"] == "remember" and out["params"]["people"] == ["Goodspouse"]


def test_records_with_head_cites_and_optional_fields():
    reply = ('LOOP asked_of_me\nsummary: Review the patch\ncite: [3] "can you review the patch before Friday"\n'
             'resolved: no\nresolved_cite: -\n\nLOOP: waiting on\nsummary: Get SSO dates\n'
             'cite: [5] “when is SSO launching?”\nresolved: yes\nresolved_cite: [6] "SSO launches Oct 20"')
    out, problems = LOOPS.parse(reply)
    assert problems == []
    assert out["loops"][0] == {"kind": "asked_of_me", "summary": "Review the patch", "ref": 3,
                               "quote": "can you review the patch before Friday", "resolved": False}
    second = out["loops"][1]
    assert second["kind"] == "waiting_on" and second["quote"] == "when is SSO launching?"
    assert (second["resolved_ref"], second["resolved_quote"]) == (6, "SSO launches Oct 20")


def test_none_means_no_records():
    assert LOOPS.parse("NONE") == ({"loops": []}, [])


def test_records_come_after_top_level_fields():
    out, problems = ROUTE.parse("intent: loop_update\ntext: -\nALSO remember\ntext: Sam is my neighbor.")
    assert problems == []
    assert out["also"] == [{"intent": "remember", "text": "Sam is my neighbor."}]
    assert out["params"]["text"] is None


def test_problems_name_the_field():
    assert ROUTE.parse("people: Alex")[1] == ["missing `intent`"]
    assert "`intent` should be one of search, remember, loop_update" in ROUTE.parse("intent: dance")[1][0]
    problems = LOOPS.parse("LOOP asked_of_me\nsummary: x\ncite: [x] nope\nresolved: maybe")[1]
    assert any("`LOOP cite`" in p for p in problems) and any("`LOOP resolved`" in p for p in problems)


def test_instructions_list_fields_records_and_example():
    text = LOOPS.instructions()
    assert "not JSON" in text and "LOOP <kind: one of asked_of_me, waiting_on>" in text
    assert 'cite: [n] "words copied exactly from source n"' in text and "NONE" in text
    assert "intent: one of search, remember, loop_update" in ROUTE.instructions()
    assert "people: list, separated by ;, or -" in ROUTE.instructions()
    assert ROUTE.instructions().endswith("Example:\nintent: search\npeople: -\nsince: -\ntext: -")
