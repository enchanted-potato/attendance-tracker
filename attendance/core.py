from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AttendanceDay

DEFAULT_TARGET_PCT = 60.0


class DayStatus(str, Enum):
    """Status a single working day can be logged with."""

    OFFICE = "office"
    REMOTE = "remote"
    LEAVE = "leave"
    HOLIDAY = "holiday"

    @classmethod
    def choices(cls) -> list[str]:
        """Return all valid status values.

        :returns: the string value of every :class:`DayStatus` member.
        :rtype: list[str]
        """
        return [s.value for s in cls]


#: Statuses that count toward the "working days" denominator (i.e. days the
#: employee was expected to either be in office or working remotely).
COUNTED_STATUSES = {DayStatus.OFFICE, DayStatus.REMOTE}
#: Statuses that explicitly remove a weekday from the denominator.
EXCLUDED_STATUSES = {DayStatus.LEAVE, DayStatus.HOLIDAY}


def is_weekend(d: date) -> bool:
    """Check whether a date falls on a Saturday or Sunday.

    :param d: the date to check.
    :type d: datetime.date
    :returns: ``True`` if ``d`` is a Saturday or Sunday.
    :rtype: bool
    """
    return d.weekday() >= 5  # Saturday=5, Sunday=6


def quarter_bounds(d: date) -> tuple[int, int, date, date]:
    """Compute the calendar quarter containing a date.

    :param d: any date within the quarter of interest.
    :type d: datetime.date
    :returns: a ``(year, quarter_number, start_date, end_date)`` tuple, where
        ``start_date`` and ``end_date`` are inclusive.
    :rtype: tuple[int, int, datetime.date, datetime.date]
    """
    q = (d.month - 1) // 3 + 1
    start_month = 3 * (q - 1) + 1
    start = date(d.year, start_month, 1)
    if q == 4:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, start_month + 3, 1) - timedelta(days=1)
    return d.year, q, start, end


def parse_quarter(label: str) -> tuple[date, date]:
    """Parse a ``YYYY-Qn`` label into its date bounds.

    :param label: quarter label, e.g. ``"2026-Q3"``.
    :type label: str
    :returns: a ``(start_date, end_date)`` tuple, inclusive.
    :rtype: tuple[datetime.date, datetime.date]
    :raises ValueError: if ``label`` isn't a valid ``YYYY-Qn`` string.
    """
    try:
        year_str, q_str = label.upper().split("-Q")
        year = int(year_str)
        q = int(q_str)
        if q not in (1, 2, 3, 4):
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid quarter label {label!r}, expected e.g. '2026-Q3'") from exc
    start_month = 3 * (q - 1) + 1
    start = date(year, start_month, 1)
    end = date(year, 12, 31) if q == 4 else date(year, start_month + 3, 1) - timedelta(days=1)
    return start, end


def weekdays_between(start: date, end: date) -> list[date]:
    """List every Monday-Friday date in an inclusive range.

    :param start: first date of the range (inclusive).
    :type start: datetime.date
    :param end: last date of the range (inclusive).
    :type end: datetime.date
    :returns: all weekday (Mon-Fri) dates between ``start`` and ``end``,
        in ascending order. Empty if ``end`` is before ``start``.
    :rtype: list[datetime.date]
    """
    if end < start:
        return []
    days = []
    current = start
    while current <= end:
        if not is_weekend(current):
            days.append(current)
        current += timedelta(days=1)
    return days


@dataclass
class AttendanceStats:
    """Attendance figures for a period, as of a given date.

    :ivar start: first date of the period (inclusive).
    :ivar end: last date of the period (inclusive).
    :ivar as_of: only days up to and including this date are counted.
    :ivar target_pct: the target office-attendance percentage.
    :ivar office_days: number of days logged as :attr:`DayStatus.OFFICE`.
    :ivar remote_days: number of days logged as :attr:`DayStatus.REMOTE`.
    :ivar leave_days: number of days logged as :attr:`DayStatus.LEAVE`.
    :ivar holiday_days: number of days logged as :attr:`DayStatus.HOLIDAY`.
    :ivar unlogged_weekdays: weekdays in range with no logged status at all.
    """

    start: date
    end: date
    as_of: date
    target_pct: float

    office_days: int = 0
    remote_days: int = 0
    leave_days: int = 0
    holiday_days: int = 0
    unlogged_weekdays: list[date] = field(default_factory=list)

    @property
    def counted_days(self) -> int:
        """Working days with a known office/remote status.

        :returns: the denominator used for :attr:`percentage`.
        :rtype: int
        """
        return self.office_days + self.remote_days

    @property
    def percentage(self) -> float | None:
        """Office attendance percentage over :attr:`counted_days`.

        :returns: ``100 * office_days / counted_days``, or ``None`` if no
            working days have been logged yet.
        :rtype: float | None
        """
        if self.counted_days == 0:
            return None
        return 100.0 * self.office_days / self.counted_days

    @property
    def on_track(self) -> bool | None:
        """Whether :attr:`percentage` currently meets :attr:`target_pct`.

        :returns: ``None`` if :attr:`percentage` is undefined.
        :rtype: bool | None
        """
        pct = self.percentage
        if pct is None:
            return None
        return pct >= self.target_pct

    @property
    def remaining_weekdays(self) -> int:
        """Weekdays strictly after :attr:`as_of` through :attr:`end`.

        This is an upper bound on remaining working days: it doesn't yet
        know about future leave/holidays you haven't logged.

        :rtype: int
        """
        if self.as_of >= self.end:
            return 0
        return len(weekdays_between(self.as_of + timedelta(days=1), self.end))

    @property
    def office_days_needed(self) -> int | None:
        """Additional office days needed to reach the target by period end.

        Assumes every remaining weekday turns out to be a working day
        (best case for the denominator).

        :returns: the minimum number of the remaining weekdays that would
            need to be logged as office days to hit :attr:`target_pct`, or
            ``None`` if there are no working days to project over at all.
        :rtype: int | None
        """
        remaining = self.remaining_weekdays
        total_possible = self.counted_days + remaining
        if total_possible == 0:
            return None
        needed = math.ceil((self.target_pct / 100.0) * total_possible - self.office_days)
        needed = max(0, needed)
        return needed

    @property
    def target_achievable(self) -> bool | None:
        """Whether the target is still reachable by period end.

        :returns: ``False`` if even attending every remaining weekday
            wouldn't reach :attr:`target_pct`; ``None`` if undefined.
        :rtype: bool | None
        """
        needed = self.office_days_needed
        if needed is None:
            return None
        return needed <= self.remaining_weekdays

    def to_dict(self) -> dict:
        """Serialize these stats to a JSON-friendly dict.

        :returns: all fields and derived properties, with dates as ISO
            strings.
        :rtype: dict
        """
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "as_of": self.as_of.isoformat(),
            "target_pct": self.target_pct,
            "office_days": self.office_days,
            "remote_days": self.remote_days,
            "leave_days": self.leave_days,
            "holiday_days": self.holiday_days,
            "counted_days": self.counted_days,
            "percentage": self.percentage,
            "on_track": self.on_track,
            "unlogged_weekdays": [d.isoformat() for d in self.unlogged_weekdays],
            "remaining_weekdays": self.remaining_weekdays,
            "office_days_needed": self.office_days_needed,
            "target_achievable": self.target_achievable,
        }


def compute_stats(
    session: Session,
    start: date,
    end: date,
    as_of: date | None = None,
    target_pct: float = DEFAULT_TARGET_PCT,
) -> AttendanceStats:
    """Compute attendance stats for a period.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param start: first date of the period (inclusive).
    :type start: datetime.date
    :param end: last date of the period (inclusive).
    :type end: datetime.date
    :param as_of: only count logged days up to and including this date.
        Defaults to ``end``, or today if that's earlier.
    :type as_of: datetime.date | None
    :param target_pct: target office-attendance percentage.
    :type target_pct: float
    :returns: the computed :class:`AttendanceStats`.
    :rtype: AttendanceStats
    """
    if as_of is None:
        as_of = min(end, date.today())
    as_of = max(start - timedelta(days=1), min(as_of, end))

    stats = AttendanceStats(start=start, end=end, as_of=as_of, target_pct=target_pct)
    if as_of < start:
        logger.debug("as_of {} is before period start {}; nothing to count", as_of, start)
        return stats

    rows = session.execute(
        select(AttendanceDay).where(AttendanceDay.day >= start, AttendanceDay.day <= as_of)
    ).scalars().all()
    logged = {row.day: row.status for row in rows}

    for status in logged.values():
        if status == DayStatus.OFFICE.value:
            stats.office_days += 1
        elif status == DayStatus.REMOTE.value:
            stats.remote_days += 1
        elif status == DayStatus.LEAVE.value:
            stats.leave_days += 1
        elif status == DayStatus.HOLIDAY.value:
            stats.holiday_days += 1

    for d in weekdays_between(start, as_of):
        if d not in logged:
            stats.unlogged_weekdays.append(d)

    logger.info(
        "Computed stats for {}..{} (as of {}): {:.1f}% over {} counted days, {} unlogged",
        start,
        end,
        as_of,
        stats.percentage if stats.percentage is not None else float("nan"),
        stats.counted_days,
        len(stats.unlogged_weekdays),
    )
    return stats


def compute_quarter_stats(
    session: Session,
    as_of: date | None = None,
    target_pct: float = DEFAULT_TARGET_PCT,
) -> AttendanceStats:
    """Compute attendance stats for the calendar quarter containing ``as_of``.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param as_of: the reference date; defaults to today. Also used as the
        ``as_of`` cutoff for :func:`compute_stats`.
    :type as_of: datetime.date | None
    :param target_pct: target office-attendance percentage.
    :type target_pct: float
    :returns: the computed :class:`AttendanceStats` for that quarter.
    :rtype: AttendanceStats
    """
    ref = as_of or date.today()
    _, _, start, end = quarter_bounds(ref)
    return compute_stats(session, start, end, as_of=as_of, target_pct=target_pct)
