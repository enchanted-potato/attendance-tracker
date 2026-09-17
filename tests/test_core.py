from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from attendance.core import (
    DayStatus,
    compute_stats,
    is_weekend,
    parse_quarter,
    quarter_bounds,
    weekdays_between,
)
from attendance.db import get_engine
from attendance.service import delete_day, upsert_day


@pytest.fixture
def session():
    engine = get_engine(":memory:")
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as s:
        yield s


def test_quarter_bounds():
    assert quarter_bounds(date(2026, 9, 17)) == (2026, 3, date(2026, 7, 1), date(2026, 9, 30))
    assert quarter_bounds(date(2026, 1, 1)) == (2026, 1, date(2026, 1, 1), date(2026, 3, 31))
    assert quarter_bounds(date(2026, 12, 31)) == (2026, 4, date(2026, 10, 1), date(2026, 12, 31))


def test_parse_quarter():
    assert parse_quarter("2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    with pytest.raises(ValueError):
        parse_quarter("not-a-quarter")


def test_weekdays_between_excludes_weekends():
    # Mon 2026-09-14 .. Sun 2026-09-20
    days = weekdays_between(date(2026, 9, 14), date(2026, 9, 20))
    assert days == [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]


def test_is_weekend():
    assert is_weekend(date(2026, 9, 19))  # Saturday
    assert not is_weekend(date(2026, 9, 18))  # Friday


def test_upsert_rejects_weekend(session):
    with pytest.raises(ValueError):
        upsert_day(session, date(2026, 9, 19), DayStatus.OFFICE)


def test_compute_stats_basic(session):
    # Mon-Fri of one week: office, office, remote, leave, holiday
    upsert_day(session, date(2026, 9, 14), DayStatus.OFFICE)
    upsert_day(session, date(2026, 9, 15), DayStatus.OFFICE)
    upsert_day(session, date(2026, 9, 16), DayStatus.REMOTE)
    upsert_day(session, date(2026, 9, 17), DayStatus.LEAVE)
    upsert_day(session, date(2026, 9, 18), DayStatus.HOLIDAY)

    stats = compute_stats(session, date(2026, 9, 14), date(2026, 9, 18), as_of=date(2026, 9, 18))

    assert stats.office_days == 2
    assert stats.remote_days == 1
    assert stats.leave_days == 1
    assert stats.holiday_days == 1
    assert stats.counted_days == 3
    assert stats.percentage == pytest.approx(200 / 3)
    assert stats.unlogged_weekdays == []


def test_compute_stats_unlogged_weekdays_flagged(session):
    upsert_day(session, date(2026, 9, 14), DayStatus.OFFICE)
    # 15th-18th left unlogged
    stats = compute_stats(session, date(2026, 9, 14), date(2026, 9, 18), as_of=date(2026, 9, 18))
    assert stats.counted_days == 1
    assert stats.unlogged_weekdays == [
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]


def test_target_progress_math(session):
    # 1 office day logged out of 1 counted day, target 60%.
    upsert_day(session, date(2026, 9, 14), DayStatus.OFFICE)
    stats = compute_stats(
        session,
        date(2026, 9, 14),
        date(2026, 9, 18),
        as_of=date(2026, 9, 14),
        target_pct=60.0,
    )
    # 4 remaining weekdays (15th-18th), currently 1/1 office.
    assert stats.remaining_weekdays == 4
    # total_possible = 1 + 4 = 5; need ceil(0.6*5 - 1) = ceil(2) = 2
    assert stats.office_days_needed == 2
    assert stats.target_achievable is True


def test_target_unreachable(session):
    upsert_day(session, date(2026, 9, 14), DayStatus.REMOTE)
    upsert_day(session, date(2026, 9, 15), DayStatus.REMOTE)
    upsert_day(session, date(2026, 9, 16), DayStatus.REMOTE)
    upsert_day(session, date(2026, 9, 17), DayStatus.REMOTE)
    stats = compute_stats(
        session,
        date(2026, 9, 14),
        date(2026, 9, 18),
        as_of=date(2026, 9, 17),
        target_pct=60.0,
    )
    # 4 remote so far, 1 remaining weekday (18th). Even attending it: 1/5 = 20% < 60%.
    assert stats.remaining_weekdays == 1
    assert stats.office_days_needed == 3
    assert stats.target_achievable is False


def test_delete_day(session):
    upsert_day(session, date(2026, 9, 14), DayStatus.OFFICE)
    assert delete_day(session, date(2026, 9, 14)) is True
    assert delete_day(session, date(2026, 9, 14)) is False
