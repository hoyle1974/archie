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


def test_near_is_one_typo_apart():
    from archie.names import near

    assert near("WorkPersoon", "Workperson") and near("Prya", "Priya") and near("Sarha", "Sarah") and near("WorkPersan", "Workperson")
    assert not near("Workperson", "Workperson")  # the same name is a match, not a near miss
    assert not near("Ken", "Kim") and not near("Kenn", "Ken")  # too short to guess
    assert not near("Workperson", "Kevin") and not near("Arjun", "Aaron")


def test_directory_near_finds_one_person_by_a_typo(tmp_path):
    from archie.derive.people import PeopleDirectory

    d = PeopleDirectory(meta={"workperson_acorn": {"name": "Workperson Acorn"}, "priya_sharma": {"name": "Priya Sharma"},
                              "keira_bell": {"name": "Keira Bell"}})
    assert d.near("WorkPersoon") == ["workperson_acorn"]
    assert d.near("Prya") == ["priya_sharma"]
    assert d.near("Zebulon") == []
