from archie.names import name_forms, name_key


def test_name_key_drops_possessives_and_edge_punctuation():
    assert name_key("Workperson's") == "workperson"
    assert name_key("Workperson’s") == "workperson"
    assert name_key("Wes'") == "wes"
    assert name_key("(Priya)") == "priya"
    assert name_key("Workpersons") == "workpersons"  # no apostrophe: the key keeps the s


def test_name_forms_adds_the_s_less_form():
    assert name_forms("Workpersons") == {"workpersons", "workperson"}
    assert name_forms("Workperson's") == {"workperson's", "workperson"}
    assert "james" in name_forms("James") and "jame" in name_forms("James")  # only widens what was heard
    assert name_forms("Ross") >= {"ross"}
    assert name_forms("is") == {"is"}  # short words get no extra form
    assert name_forms("Priya S") == {"priya s"}  # an initial S isn't a possessive
