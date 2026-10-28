from detect.signatures import extract_reverted_user, is_revert, is_self_revert
from detect.tests.fixtures import HUGGLE_IP, TWINKLE_OTHER, UNDO_SOMEUSER


def test_plain_edit_is_not_a_revert() -> None:
    assert is_revert("fix typo") is False
    assert is_revert("service note about the article") is False
    assert is_revert("previously discussed on talk") is False
    assert extract_reverted_user("fix typo") is None


def test_twinkle_revert_extracts_user() -> None:
    assert is_revert(TWINKLE_OTHER) is True
    assert extract_reverted_user(TWINKLE_OTHER) == "OtherUser"


def test_huggle_revert_extracts_ip() -> None:
    assert is_revert(HUGGLE_IP) is True
    assert extract_reverted_user(HUGGLE_IP) == "1.2.3.4"


def test_undo_comment_extracts_contributions_user() -> None:
    assert is_revert(UNDO_SOMEUSER) is True
    assert extract_reverted_user(UNDO_SOMEUSER) == "SomeUser"


def test_revert_tags_count_without_a_matching_comment() -> None:
    assert is_revert("tweaked wording", ("mw-rollback",)) is True
    assert is_revert("", ("mw-undo",)) is True
    assert is_revert("copy edit", ("mw-manual-revert",)) is True
    assert is_revert("copy edit", ("mw-reverted",)) is True
    assert is_revert("copy edit", ("mw-new-redirect",)) is False


def test_revert_pattern_is_case_insensitive_and_respects_rv_boundary() -> None:
    assert is_revert("REVERTED") is True
    assert is_revert("rv") is True
    assert is_revert("Please RV: vandalism") is True
    assert is_revert("rollback of last change") is True
    assert is_revert("Twinkle did this") is True


def test_self_revert_when_editor_matches_target() -> None:
    assert is_self_revert("SomeUser", "SomeUser", UNDO_SOMEUSER) is True
    assert is_self_revert("Some User", "Some_User", UNDO_SOMEUSER) is True
    assert is_self_revert("Patroller", "SomeUser", UNDO_SOMEUSER) is False


def test_self_rv_comment_without_a_target_is_excluded() -> None:
    assert is_self_revert("Alice", None, "self-rv") is True
    assert is_self_revert("Alice", None, "Self RV of my mistake") is True
    assert is_self_revert("Alice", "Bob", f"{TWINKLE_OTHER} self-rv") is False
