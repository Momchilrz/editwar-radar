from datetime import UTC, datetime, timedelta

from detect.engine import WarEngine
from detect.tests.fixtures import T0, make_edit
from detect.windows import DAILY_MIN_REVERTS, FOUR_HOUR_MIN_REVERTS, clock_four_hours, utc_today


def test_four_hour_block_steps_forward_on_the_hour() -> None:
    at_2030 = datetime(2026, 6, 1, 20, 30, tzinfo=UTC)
    start, end = clock_four_hours(at_2030)
    assert start == datetime(2026, 6, 1, 16, 0, tzinfo=UTC)
    assert end == at_2030

    at_2100 = datetime(2026, 6, 1, 21, 0, tzinfo=UTC)
    start, end = clock_four_hours(at_2100)
    assert start == datetime(2026, 6, 1, 17, 0, tzinfo=UTC)
    assert end == at_2100


def test_utc_today_starts_at_midnight() -> None:
    now = datetime(2026, 6, 1, 20, 30, tzinfo=UTC)
    start, end = utc_today(now)
    assert start == datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    assert end == now


def test_three_reverts_stay_off_the_four_hour_board() -> None:
    engine = WarEngine(timedelta(hours=26), min_reverts=FOUR_HOUR_MIN_REVERTS)
    now = T0 + timedelta(hours=2)
    for index, user in enumerate(("Alice", "Bob", "Cara")):
        engine.observe(
            make_edit(
                user=user,
                comment=f"Reverted 1 edit by Patroller ([[WP:TW|TW]]) #{index}",
                event_id=f"r{index}",
                timestamp=T0 + timedelta(minutes=index),
            ),
            now=now,
        )
    start, end = clock_four_hours(now)
    assert engine.board(start, end, min_reverts=FOUR_HOUR_MIN_REVERTS).total == 0
    engine.observe(
        make_edit(
            user="Dana",
            comment="Reverted 1 edit by Patroller ([[WP:TW|TW]])",
            event_id="r3",
            timestamp=T0 + timedelta(minutes=10),
        ),
        now=now,
    )
    assert engine.board(start, end, min_reverts=FOUR_HOUR_MIN_REVERTS).total == 1


def test_slice_keeps_older_reverts_for_the_daily_board() -> None:
    engine = WarEngine(timedelta(hours=26))
    morning = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    evening = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
    for index in range(DAILY_MIN_REVERTS):
        engine.observe(
            make_edit(
                user=f"Editor{index}",
                comment="Reverted 1 edit by Vandal ([[WP:TW|TW]])",
                event_id=f"d{index}",
                timestamp=morning + timedelta(minutes=index),
            ),
            now=evening,
        )
    day_start, _day_end = utc_today(evening)
    assert engine.board(day_start, evening, min_reverts=DAILY_MIN_REVERTS).total == 1
    block_start, _block_end = clock_four_hours(evening)
    assert engine.board(block_start, evening, min_reverts=FOUR_HOUR_MIN_REVERTS).total == 0
