from __future__ import annotations

from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AttendanceDay(Base):
    """A single calendar day with a logged status.

    Only days that matter for the calculation need a row: weekends are
    derived from the date itself and never need to be logged.
    """

    __tablename__ = "attendance_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"AttendanceDay(day={self.day!r}, status={self.status!r})"
