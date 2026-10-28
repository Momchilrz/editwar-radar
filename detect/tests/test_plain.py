from detect.plain import plain_comment

_UNDID = (
    "Undid revision [[Special:Diff/1382403333|1382403333]] by "
    "[[Special:Contributions/Binksternet|Binksternet]] ([[User talk:Binksternet|talk]]) "
    "On the new wave and punk article I can agree with you. But not here, the genre "
    "[[WP:EXPLICITGENRE]] are sourced, not fair"
)
_REVERT = (
    "Reverted 1 edit by [[Special:Contributions/Ezéchiel Péquay|Ezéchiel Péquay]] "
    "([[User talk:Ezéchiel Péquay|talk]]) to last revision by Binksternet"
)
_TWINKLE = "Reverted 1 edit by OtherUser ([[WP:TW|TW]])"


def test_undo_comment_keeps_the_note_and_drops_wiki_syntax() -> None:
    text = plain_comment(_UNDID)
    assert "[[" not in text
    assert "Special:" not in text
    assert "User talk" not in text
    assert "Binksternet. On the new wave" in text
    assert "new wave and punk" in text
    assert "sourced, not fair" in text


def test_revert_comment_names_people_in_plain_words() -> None:
    text = plain_comment(_REVERT)
    assert "[[" not in text
    assert "Ezéchiel Péquay" in text
    assert "last version by Binksternet" in text
    assert text.startswith("Reverted an edit by")


def test_twinkle_tag_is_removed() -> None:
    text = plain_comment(_TWINKLE)
    assert "WP:" not in text
    assert "TW" not in text
    assert "OtherUser" in text
