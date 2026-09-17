from __future__ import annotations

from datetime import date
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .core import DEFAULT_TARGET_PCT, DayStatus, compute_stats, parse_quarter, quarter_bounds
from .db import get_session_factory
from .service import delete_day, get_day, list_days, upsert_day

app = FastAPI(title="Attendance Tracker", version="0.1.0")

_session_factory = get_session_factory()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped SQLAlchemy session.

    :yields: an open session, closed automatically after the request.
    :rtype: Iterator[sqlalchemy.orm.Session]
    """
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


class DayIn(BaseModel):
    """Request body for creating or updating a logged day."""

    day: date
    status: DayStatus
    note: str | None = None


class DayOut(BaseModel):
    """Response body describing a logged day."""

    day: date
    status: DayStatus
    note: str | None = None


class StatsOut(BaseModel):
    """Response body for the ``/stats`` endpoint."""

    start: date
    end: date
    as_of: date
    target_pct: float
    office_days: int
    remote_days: int
    leave_days: int
    holiday_days: int
    counted_days: int
    percentage: float | None
    on_track: bool | None
    unlogged_weekdays: list[date]
    remaining_weekdays: int
    office_days_needed: int | None
    target_achievable: bool | None


def _resolve_period(quarter: str | None, start: date | None, end: date | None) -> tuple[date, date]:
    """Resolve a query-parameter period selection into concrete dates.

    :param quarter: a ``YYYY-Qn`` label, or ``None``.
    :type quarter: str | None
    :param start: an explicit start date, or ``None``.
    :type start: datetime.date | None
    :param end: an explicit end date, or ``None``.
    :type end: datetime.date | None
    :returns: a ``(start_date, end_date)`` tuple. Falls back to the current
        calendar quarter if neither ``quarter`` nor ``start``/``end`` is
        given.
    :rtype: tuple[datetime.date, datetime.date]
    :raises fastapi.HTTPException: 400 if ``quarter`` is malformed, or if
        only one of ``start``/``end`` is given.
    """
    if quarter:
        try:
            return parse_quarter(quarter)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if start and end:
        return start, end
    if start or end:
        raise HTTPException(status_code=400, detail="start and end must be given together")
    _, _, qstart, qend = quarter_bounds(date.today())
    return qstart, qend


@app.put("/days/{day}", response_model=DayOut)
def put_day(day: date, payload: DayIn, db: Session = Depends(get_db)) -> DayOut:
    """Create or update the logged status for a day.

    :param day: the date to log, from the URL path.
    :type day: datetime.date
    :param payload: the request body; ``payload.day`` must match ``day``.
    :type payload: DayIn
    :param db: request-scoped database session.
    :type db: sqlalchemy.orm.Session
    :returns: the stored day.
    :rtype: DayOut
    :raises fastapi.HTTPException: 400 if the path and body dates disagree,
        or if ``day`` is a weekend.
    """
    if day != payload.day:
        raise HTTPException(status_code=400, detail="path day and body day must match")
    try:
        row = upsert_day(db, day, payload.status, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DayOut(day=row.day, status=DayStatus(row.status), note=row.note)


@app.get("/days/{day}", response_model=DayOut)
def read_day(day: date, db: Session = Depends(get_db)) -> DayOut:
    """Fetch the logged status for a single day.

    :param day: the date to look up.
    :type day: datetime.date
    :param db: request-scoped database session.
    :type db: sqlalchemy.orm.Session
    :returns: the stored day.
    :rtype: DayOut
    :raises fastapi.HTTPException: 404 if that day hasn't been logged.
    """
    row = get_day(db, day)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return DayOut(day=row.day, status=DayStatus(row.status), note=row.note)


@app.delete("/days/{day}", status_code=204)
def remove_day(day: date, db: Session = Depends(get_db)) -> None:
    """Remove a logged day.

    :param day: the date to remove.
    :type day: datetime.date
    :param db: request-scoped database session.
    :type db: sqlalchemy.orm.Session
    :raises fastapi.HTTPException: 404 if that day hasn't been logged.
    """
    if not delete_day(db, day):
        raise HTTPException(status_code=404, detail="not found")


@app.get("/days", response_model=list[DayOut])
def read_days(start: date, end: date, db: Session = Depends(get_db)) -> list[DayOut]:
    """List logged days within an inclusive range.

    :param start: first date of the range (inclusive).
    :type start: datetime.date
    :param end: last date of the range (inclusive).
    :type end: datetime.date
    :param db: request-scoped database session.
    :type db: sqlalchemy.orm.Session
    :returns: matching days in ascending date order.
    :rtype: list[DayOut]
    """
    rows = list_days(db, start, end)
    return [DayOut(day=r.day, status=DayStatus(r.status), note=r.note) for r in rows]


@app.get("/stats", response_model=StatsOut)
def read_stats(
    quarter: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    target: float = DEFAULT_TARGET_PCT,
    db: Session = Depends(get_db),
) -> StatsOut:
    """Compute attendance stats for a period.

    :param quarter: a ``YYYY-Qn`` label; alternative to ``start``/``end``.
    :type quarter: str | None
    :param start: first date of the period (inclusive).
    :type start: datetime.date | None
    :param end: last date of the period (inclusive).
    :type end: datetime.date | None
    :param as_of: only count logged days up to and including this date.
        Defaults to today.
    :type as_of: datetime.date | None
    :param target: target office-attendance percentage.
    :type target: float
    :param db: request-scoped database session.
    :type db: sqlalchemy.orm.Session
    :returns: the computed stats.
    :rtype: StatsOut
    """
    period_start, period_end = _resolve_period(quarter, start, end)
    logger.debug("GET /stats for {}..{} as_of={} target={}", period_start, period_end, as_of, target)
    s = compute_stats(db, period_start, period_end, as_of=as_of, target_pct=target)
    return StatsOut(**s.to_dict())
