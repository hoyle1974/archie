from archie.derive.ignore import on_list


def test_on_list_matches_addresses_and_whole_domains():
    assert on_list("Ken@Acme.example", ["ken@acme.example"])
    assert on_list("x@spam.example", ["@spam.example"]) and on_list("x@SPAM.example", ["@Spam.Example"])
    assert not on_list("x@notspam.example", ["@spam.example"])
    assert not on_list("", ["@spam.example"]) and not on_list("ken@acme.example", [])
