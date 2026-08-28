from datetime import datetime

from app.services.room_booking import periods_overlap


def test_overlapping_room_periods_conflict():
    assert periods_overlap(
        datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 10, 0),
        datetime(2026, 9, 1, 9, 30), datetime(2026, 9, 1, 10, 30),
    )


def test_adjacent_room_periods_do_not_conflict():
    assert not periods_overlap(
        datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 10, 0),
        datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0),
    )
