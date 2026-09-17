from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import DayStatus, is_weekend
from .models import AttendanceDay


def upsert_day(session: Session, day: date, status: DayStatus, note: str | None = None) -> AttendanceDay:
    if is_weekend(day):
        raise ValueError(f"{day.isoformat()} is a weekend; weekends aren't tracked")
    row = session.get(AttendanceDay, day)
    if row is None:
        row = AttendanceDay(day=day, status=status.value, note=note)
        session.add(row)
    else:
        row.status = status.value
        row.note = note
    session.commit()
    return row


def delete_day(session: Session, day: date) -> bool:
    row = session.get(AttendanceDay, day)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def get_day(session: Session, day: date) -> AttendanceDay | None:
    return session.get(AttendanceDay, day)


def list_days(session: Session, start: date, end: date) -> list[AttendanceDay]:
    return list(
        session.execute(
            select(AttendanceDay)
            .where(AttendanceDay.day >= start, AttendanceDay.day <= end)
            .order_by(AttendanceDay.day)
        ).scalars()
    )
