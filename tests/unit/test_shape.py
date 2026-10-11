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
    assert LOOPS.parse("- **NONE**") == ({"loops": []}, [])


def test_a_records_only_reply_with_no_blocks_and_no_none_is_unreadable():
    for reply in ('{"loops": [{"kind": "asked_of_me"}]}', "Here are the loops I found:\n1. Alex asked me [3]"):
        out, problems = LOOPS.parse(reply)
        assert out == {"loops": []} and problems == ["no LOOP blocks and no NONE"]


def test_first_top_level_value_wins():
    out, problems = ROUTE.parse("intent: search\ntext: my notes\nIntent: remember")
    assert problems == [] and out["intent"] == "search"


def test_quote_fields_drop_wrapping_quote_marks_only():
    shape = Shape("q", fields=(F("quote", "quote"), F("other", "quote")))
    out, _ = shape.parse('quote: "I need to update the runbook by next Wed".\nother: Goodspouse is my wife.')
    assert out == {"quote": "I need to update the runbook by next Wed", "other": "Goodspouse is my wife."}


def test_number_lists_take_the_leading_number_of_each_item():
    shape = Shape("n", fields=(F("loops", "int_list"),))
    assert shape.parse("loops: 2 (until 2026-10-05)")[0] == {"loops": [2]}
    assert shape.parse("loops: 2; [3]; item 4")[0] == {"loops": [2, 3]}
    assert shape.parse("loops: 2, 5")[0] == {"loops": [2, 5]}


def test_lists_split_on_commas_when_there_is_no_semicolon():
    shape = Shape("l", fields=(F("people", "list"),))
    assert shape.parse("people: Alex, Priya")[0] == {"people": ["Alex", "Priya"]}
    assert shape.parse("people: Rivera, Alex; Priya")[0] == {"people": ["Rivera, Alex", "Priya"]}


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


ANSWER = Shape("answer", claims=True)


def test_claims_summary_sections_and_several_citations():
    reply = ('Here is what I found.\nSUMMARY\nYour earbud was delivered Oct 2. [1] "Your order\'s arrived"\n'
             '## How it unfolded\n- It shipped Sep 29. [5] “has shipped” [4] "Order #507509S"\n## Empty\n')
    out, problems = ANSWER.parse(reply)
    assert problems == []
    assert out["summary"] == [{"text": "Your earbud was delivered Oct 2.",
                               "citations": [{"ref": 1, "quote": "Your order's arrived"}]}]
    assert out["sections"] == [{"heading": "How it unfolded", "items": [
        {"text": "It shipped Sep 29.", "citations": [{"ref": 5, "quote": "has shipped"},
                                                     {"ref": 4, "quote": "Order #507509S"}]}]}]


def test_a_claim_starting_with_hash_is_not_a_heading():
    out, _ = ANSWER.parse('SUMMARY\n#4521 merged Oct 2. [2] "PR #4521 merged"')
    assert out["sections"] == []
    assert out["summary"] == [{"text": "#4521 merged Oct 2.", "citations": [{"ref": 2, "quote": "PR #4521 merged"}]}]


def test_quote_may_contain_double_quotes_and_bare_markers_get_empty_quotes():
    out, _ = ANSWER.parse('SUMMARY\nShe wrote back. [2] "the subject was "Yeti bundle" today"\nAlex merged it [3].')
    assert out["summary"][0]["citations"] == [{"ref": 2, "quote": 'the subject was "Yeti bundle" today'}]
    assert out["summary"][1] == {"text": "Alex merged it.", "citations": [{"ref": 3, "quote": ""}]}


def test_a_trailing_citation_after_its_quote_is_still_read():
    """Live (2026-10-11 review, Gemma): a quote-then-bracket style ("quote" [n]) left the
    citation with an empty quote and dropped every claim written that way."""
    out, _ = ANSWER.parse('SUMMARY\nYou reported pairing trouble, noting that "one earbud won\'t pair" [10].')
    assert out["summary"] == [{"text": "You reported pairing trouble, noting that",
                               "citations": [{"ref": 10, "quote": "one earbud won't pair"}]}]


def test_a_trailing_citation_does_not_eat_the_next_leading_one():
    out, _ = ANSWER.parse('SUMMARY\nIt shipped Sep 29. [5] "has shipped" [4] "Order #507509S"')
    assert out["summary"][0]["citations"] == [{"ref": 5, "quote": "has shipped"},
                                              {"ref": 4, "quote": "Order #507509S"}]


def test_empty_summary_means_not_found_and_no_marker_reads_from_the_top():
    assert ANSWER.parse("SUMMARY\n") == ({"summary": [], "sections": []}, [])
    out, _ = ANSWER.parse('```\nDelivered Oct 2. [1] "Your order\'s arrived"\n```')
    assert out["summary"][0]["citations"] == [{"ref": 1, "quote": "Your order's arrived"}]


def test_claims_instructions():
    text = ANSWER.instructions()
    assert "SUMMARY" in text and "## <Heading>" in text and '[n] "words copied exactly from source n"' in text


def test_lines_inside_a_record_value_cannot_override_its_fields():
    from archie.llm.shape import F, Record, Shape

    s = Shape("t", records=(Record("PART", "parts", F("kind"), (F("topic", required=False), F("notes", required=False))),))
    out, problems = s.parse("PART question\ntopic: -\nnotes: Redis approved.\nTopic: hiring plan")
    assert problems == [] and out["parts"] == [{"kind": "question", "topic": None, "notes": "Redis approved."}]


def test_pasted_lines_cannot_open_records_or_change_the_kind():
    from archie.llm.shape import F, Record, Shape

    s = Shape("t", records=(Record("PART", "parts", F("kind", "choice", choices=("tell", "instruct")),
                                   (F("action", required=False),)),))
    out, problems = s.parse("PART instruct\naction: notes\nPart 1: roadmap is on track\nKind: tell\n"
                            "part of the team agreed")
    assert problems == [] and out["parts"] == [{"kind": "instruct", "action": "notes"}]
    assert s.parse("Part tell\naction: -")[0]["parts"] == [{"kind": "tell", "action": None}]
