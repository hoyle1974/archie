import pytest

from archie.store.fence import FenceError, get_fence, set_fence

USER_ABOVE = "## My notes\nPrefers code snippets.\n\n"
USER_BELOW = "\n## Later notes\nAsk about soccer.\n"


def fenced(inner: str) -> str:
    return f"{USER_ABOVE}<!-- archie:auto -->\n{inner}<!-- /archie:auto -->\n{USER_BELOW}"


def test_get_fence_returns_inner_text():
    assert get_fence(fenced("- fact one\n")) == "- fact one\n"


def test_get_fence_missing_returns_none():
    assert get_fence(USER_ABOVE) is None


def test_set_fence_replaces_only_inside():
    body = fenced("- old fact\n")
    out = set_fence(body, "- new fact\n")
    assert out == fenced("- new fact\n")


def test_set_fence_appends_fence_when_absent_and_keeps_user_text():
    out = set_fence(USER_ABOVE, "- fact\n")
    assert out.startswith(USER_ABOVE)
    assert get_fence(out) == "- fact\n"


def test_set_fence_adds_trailing_newline_to_content():
    assert get_fence(set_fence(fenced("x\n"), "no newline")) == "no newline\n"


def test_named_fences_are_independent():
    body = set_fence(set_fence("", "a\n", name="auto"), "b\n", name="citations")
    body = set_fence(body, "a2\n", name="auto")
    assert get_fence(body, name="auto") == "a2\n"
    assert get_fence(body, name="citations") == "b\n"


def test_unclosed_fence_raises_instead_of_guessing():
    with pytest.raises(FenceError):
        set_fence(USER_ABOVE + "<!-- archie:auto -->\nhalf\n", "x\n")


def test_duplicate_fence_raises():
    body = fenced("a\n") + "<!-- archie:auto -->\nb\n<!-- /archie:auto -->\n"
    with pytest.raises(FenceError):
        get_fence(body)


def test_user_text_outside_survives_many_rewrites_byte_for_byte():
    body = fenced("v0\n")
    for i in range(5):
        body = set_fence(body, f"v{i + 1}\n")
    assert body == fenced("v5\n")
