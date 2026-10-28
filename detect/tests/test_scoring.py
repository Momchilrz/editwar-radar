from datetime import timedelta

from detect.engine import WarEngine
from detect.scoring import war_score
from detect.tests.fixtures import HUGGLE_IP, T0, TWINKLE_OTHER, UNDO_SOMEUSER, make_edit


def _engine(**kwargs: object) -> WarEngine:
    skip_minor = bool(kwargs.get("skip_minor", False))
    min_reverts = int(kwargs.get("min_reverts", 2))  # type: ignore[arg-type]
    return WarEngine(timedelta(hours=6), min_reverts=min_reverts, skip_minor=skip_minor)


def test_score_math_mutual_is_a_flag_not_a_multiplier() -> None:
    assert war_score(reverts=2, distinct_reverters=2, mutual_pairs=0) == 10
    assert war_score(reverts=2, distinct_reverters=1, mutual_pairs=0) == 8
    assert war_score(reverts=2, distinct_reverters=2, mutual_pairs=1) == 16
    assert war_score(reverts=2, distinct_reverters=2, mutual_pairs=3) == 16
    assert war_score(reverts=5, distinct_reverters=4, mutual_pairs=1) == 29


def test_plain_edit_counts_as_edit_only() -> None:
    engine = _engine()
    result = engine.observe(make_edit(event_id="plain"), now=T0)
    assert result.reason == "counted"
    assert result.is_revert is False
    assert result.notice is None
    article = engine.article("en.wikipedia.org", "Example", T0)
    assert article is not None
    assert article.edits == 1
    assert article.reverts == 0
    assert engine.leaderboard(T0).total == 0


def test_twinkle_and_huggle_count_as_reverts() -> None:
    engine = _engine()
    twinkle = engine.observe(
        make_edit(user="TwinkleBotNot", comment=TWINKLE_OTHER, event_id="tw", title="T"),
        now=T0,
    )
    huggle = engine.observe(
        make_edit(user="HuggleUser", comment=HUGGLE_IP, event_id="hg", title="H"),
        now=T0,
    )
    assert twinkle.is_revert is True
    assert huggle.is_revert is True
    assert engine.article("en.wikipedia.org", "T", T0) is not None
    assert engine.article("en.wikipedia.org", "T", T0).reverts == 1  # type: ignore[union-attr]
    assert engine.leaderboard(T0).total == 0


def test_bot_edit_is_excluded() -> None:
    engine = _engine()
    result = engine.observe(
        make_edit(user="ClueBot", bot=True, comment=TWINKLE_OTHER, event_id="bot"),
        now=T0,
    )
    assert result.reason == "bot"
    assert engine.article("en.wikipedia.org", "Example", T0) is None
    assert engine.leaderboard(T0).total == 0


def test_self_revert_is_excluded() -> None:
    engine = _engine()
    named = engine.observe(
        make_edit(user="SomeUser", comment=UNDO_SOMEUSER, event_id="self"),
        now=T0,
    )
    shorthand = engine.observe(
        make_edit(user="Alice", comment="self-rv", event_id="shorthand", title="Other"),
        now=T0,
    )
    assert named.reason == "self_revert"
    assert shorthand.reason == "self_revert"
    assert engine.leaderboard(T0).total == 0


def test_minor_flag_is_optional() -> None:
    kept = _engine()
    assert (
        kept.observe(make_edit(minor=True, comment=TWINKLE_OTHER, event_id="m1"), now=T0).reason
        == "counted"
    )
    skipped = _engine(skip_minor=True)
    result = skipped.observe(
        make_edit(minor=True, comment=TWINKLE_OTHER, event_id="m2"),
        now=T0,
    )
    assert result.reason == "minor"


def test_mutual_pair_ignites_with_the_spec_score() -> None:
    engine = _engine()
    first = engine.observe(
        make_edit(
            user="Alice",
            comment=(
                "Undid revision [[Special:Diff/1|1]] by "
                "[[Special:Contributions/Bob|Bob]] ([[User talk:Bob|talk]])"
            ),
            event_id="a",
            timestamp=T0,
        ),
        now=T0,
    )
    second = engine.observe(
        make_edit(
            user="Bob",
            comment=(
                "Undid revision [[Special:Diff/2|2]] by "
                "[[Special:Contributions/Alice|Alice]] ([[User talk:Alice|talk]])"
            ),
            event_id="b",
            timestamp=T0 + timedelta(minutes=3),
        ),
        now=T0,
    )
    assert first.notice is None
    assert second.notice is not None
    assert second.notice.kind == "ignited"
    assert second.notice.mutual is True
    board = engine.leaderboard(T0)
    assert board.total == 1
    war = board.wars[0]
    assert war.reverts == 2
    assert war.distinct_reverters == 2
    assert war.mutual_pairs == 1
    assert war.mutual_war is True
    assert war.score == 16
    assert war.edits == 2
    assert war.war_started_at == T0
    assert set(war.reverters) == {"Alice", "Bob"}


def test_two_reverts_without_mutual_and_later_escalation() -> None:
    engine = _engine()
    engine.observe(
        make_edit(user="Alice", comment=TWINKLE_OTHER.replace("OtherUser", "Bob"), event_id="1"),
        now=T0,
    )
    ignited = engine.observe(
        make_edit(
            user="Alice",
            comment="Reverted 2 edits by Bob ([[WP:TW|TW]])",
            event_id="2",
            timestamp=T0 + timedelta(minutes=1),
        ),
        now=T0,
    )
    assert ignited.notice is not None
    assert ignited.notice.kind == "ignited"
    assert ignited.notice.mutual is False
    assert engine.leaderboard(T0).wars[0].score == 8
    mutual = engine.observe(
        make_edit(
            user="Bob",
            comment="Reverted edits by Alice (talk) ([[WP:HG|HG]]) (3.4.12)",
            event_id="3",
            timestamp=T0 + timedelta(minutes=2),
        ),
        now=T0,
    )
    assert mutual.notice is not None
    assert mutual.notice.kind == "mutual"
    war = engine.leaderboard(T0).wars[0]
    assert war.reverts == 3
    assert war.distinct_reverters == 2
    assert war.score == 19


def test_single_revert_stays_off_the_leaderboard() -> None:
    engine = _engine()
    engine.observe(make_edit(comment=HUGGLE_IP, event_id="only"), now=T0)
    assert engine.leaderboard(T0).total == 0


def test_window_expiry_removes_the_war() -> None:
    engine = _engine()
    engine.observe(make_edit(user="Alice", comment=TWINKLE_OTHER, event_id="1"), now=T0)
    engine.observe(
        make_edit(
            user="Bob",
            comment="Reverted 1 edit by Alice ([[WP:TW|TW]])",
            event_id="2",
            timestamp=T0 + timedelta(minutes=1),
        ),
        now=T0,
    )
    assert engine.leaderboard(T0).total == 1
    assert engine.leaderboard(T0 + timedelta(hours=7)).total == 0


def test_mutual_pair_expires_and_score_drops() -> None:
    engine = _engine()
    later = T0 + timedelta(hours=1)
    engine.observe(make_edit(user="Alice", comment=TWINKLE_OTHER, event_id="1"), now=later)
    engine.observe(
        make_edit(
            user="OtherUser",
            comment="Reverted 1 edit by Alice ([[WP:TW|TW]])",
            event_id="2",
            timestamp=later,
        ),
        now=later,
    )
    assert engine.leaderboard(later).wars[0].mutual_war is True
    aged = T0 + timedelta(hours=6, seconds=1)
    assert engine.leaderboard(aged).total == 0
    article = engine.article("en.wikipedia.org", "Example", aged)
    assert article is not None
    assert article.reverts == 1
    assert article.mutual_war is False
    assert article.score == 5


def test_exact_window_boundary_is_kept() -> None:
    engine = _engine()
    now = T0 + timedelta(hours=6)
    old = engine.observe(
        make_edit(timestamp=T0 - timedelta(seconds=1), event_id="old"),
        now=now,
    )
    edge = engine.observe(make_edit(timestamp=T0, event_id="edge"), now=now)
    assert old.reason == "too_old"
    assert edge.reason == "counted"


def test_duplicate_event_is_ignored() -> None:
    engine = _engine()
    edit = make_edit(comment=TWINKLE_OTHER, event_id="same", user="Alice")
    assert engine.observe(edit, now=T0).reason == "counted"
    assert engine.observe(edit, now=T0).reason == "duplicate"
    article = engine.article("en.wikipedia.org", "Example", T0)
    assert article is not None
    assert article.reverts == 1


def test_leaderboard_orders_by_score_and_filters_wiki() -> None:
    engine = _engine()
    engine.observe(
        make_edit(user="Alice", comment=TWINKLE_OTHER, event_id="e1", title="Hot"),
        now=T0,
    )
    engine.observe(
        make_edit(
            user="OtherUser",
            comment="Reverted 1 edit by Alice ([[WP:TW|TW]])",
            event_id="e2",
            title="Hot",
            timestamp=T0 + timedelta(minutes=1),
        ),
        now=T0,
    )
    engine.observe(
        make_edit(
            user="A", comment=HUGGLE_IP, event_id="d1", title="Warm", wiki="de.wikipedia.org"
        ),
        now=T0,
    )
    engine.observe(
        make_edit(
            user="B",
            comment="Reverted 1 edit by A ([[WP:TW|TW]])",
            event_id="d2",
            title="Warm",
            wiki="de.wikipedia.org",
            timestamp=T0 + timedelta(minutes=1),
        ),
        now=T0,
    )
    board = engine.leaderboard(T0)
    assert [war.title for war in board.wars] == ["Hot", "Warm"]
    assert board.wars[0].score > board.wars[1].score
    english = engine.leaderboard(T0, wiki="EN.wikipedia.org")
    assert english.total == 1
    assert english.wars[0].title == "Hot"


def test_tag_only_revert_counts_and_plain_edits_raise_the_edit_total() -> None:
    engine = _engine()
    engine.observe(make_edit(comment="added a cite", event_id="edit"), now=T0)
    engine.observe(
        make_edit(user="Alice", comment="tweaked", tags=("mw-rollback",), event_id="rb"),
        now=T0,
    )
    engine.observe(
        make_edit(
            user="Bob",
            comment="tweaked",
            tags=("mw-undo",),
            event_id="un",
            timestamp=T0 + timedelta(seconds=30),
        ),
        now=T0,
    )
    war = engine.leaderboard(T0).wars[0]
    assert war.edits == 3
    assert war.reverts == 2
    assert war.mutual_war is False
    assert war.score == 10
