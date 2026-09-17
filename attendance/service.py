from __future__ import annotations

from datetime import date

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import DayStatus, is_weekend
from .models import AttendanceDay


def upsert_day(session: Session, day: date, status: DayStatus, note: str | None = None) -> AttendanceDay:
    """Create or update the logged status for a day.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param day: the date to log. Must not be a weekend.
    :type day: datetime.date
    :param status: the status to record.
    :type status: DayStatus
    :param note: optional free-text note.
    :type note: str | None
    :returns: the created or updated row.
    :rtype: AttendanceDay
    :raises ValueError: if ``day`` is a Saturday or Sunday.
    """
    if is_weekend(day):
        logger.warning("Refusing to log {} ({}): it's a weekend", day, status.value)
        raise ValueError(f"{day.isoformat()} is a weekend; weekends aren't tracked")
    row = session.get(AttendanceDay, day)
    if row is None:
        row = AttendanceDay(day=day, status=status.value, note=note)
        session.add(row)
        logger.info("Logged {} as {}", day, status.value)
    else:
        logger.info("Updated {} from {} to {}", day, row.status, status.value)
        row.status = status.value
        row.note = note
    session.commit()
    return row


def delete_day(session: Session, day: date) -> bool:
    """Remove a logged day, if present.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param day: the date to remove.
    :type day: datetime.date
    :returns: ``True`` if a row was deleted, ``False`` if nothing was logged
        for that day.
    :rtype: bool
    """
    row = session.get(AttendanceDay, day)
    if row is None:
        logger.debug("No entry for {} to delete", day)
        return False
    session.delete(row)
    session.commit()
    logger.info("Removed logged day {}", day)
    return True


def get_day(session: Session, day: date) -> AttendanceDay | None:
    """Fetch the logged row for a single day.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param day: the date to look up.
    :type day: datetime.date
    :returns: the row, or ``None`` if that day hasn't been logged.
    :rtype: AttendanceDay | None
    """
    return session.get(AttendanceDay, day)


def list_days(session: Session, start: date, end: date) -> list[AttendanceDay]:
    """List logged days within an inclusive range, ordered by date.

    :param session: an open SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param start: first date of the range (inclusive).
    :type start: datetime.date
    :param end: last date of the range (inclusive).
    :type end: datetime.date
    :returns: matching rows in ascending date order.
    :rtype: list[AttendanceDay]
    """
    return list(
        session.execute(
            select(AttendanceDay)
            .where(AttendanceDay.day >= start, AttendanceDay.day <= end)
            .order_by(AttendanceDay.day)
        ).scalars()
    )
