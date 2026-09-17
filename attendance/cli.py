from __future__ import annotations

import sys
from datetime import date, datetime

import click
from loguru import logger

from .core import DEFAULT_TARGET_PCT, DayStatus, compute_stats, parse_quarter, quarter_bounds
from .db import get_session_factory
from .service import delete_day, list_days, upsert_day


def _parse_date(value: str) -> date:
    """Parse a CLI date argument.

    :param value: ``"today"`` or a date string in ``YYYY-MM-DD`` format.
    :type value: str
    :returns: the parsed date.
    :rtype: datetime.date
    :raises click.BadParameter: if ``value`` isn't ``"today"`` or a valid
        ``YYYY-MM-DD`` string.
    """
    if value == "today":
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise click.BadParameter(f"expected YYYY-MM-DD or 'today', got {value!r}") from exc


def _resolve_period(quarter: str | None, start: str | None, end: str | None) -> tuple[date, date]:
    """Resolve a CLI period selection into concrete start/end dates.

    :param quarter: a ``YYYY-Qn`` label, or ``None``.
    :type quarter: str | None
    :param start: a ``YYYY-MM-DD`` start date, or ``None``.
    :type start: str | None
    :param end: a ``YYYY-MM-DD`` end date, or ``None``.
    :type end: str | None
    :returns: a ``(start_date, end_date)`` tuple. Falls back to the current
        calendar quarter if neither ``quarter`` nor ``start``/``end`` is
        given.
    :rtype: tuple[datetime.date, datetime.date]
    :raises click.UsageError: if only one of ``start``/``end`` is given.
    """
    if quarter:
        return parse_quarter(quarter)
    if start and end:
        return _parse_date(start), _parse_date(end)
    if start or end:
        raise click.UsageError("--start and --end must be given together")
    _, _, qstart, qend = quarter_bounds(date.today())
    return qstart, qend


@click.group()
@click.option("--db", "db_path", default=None, help="Path to the SQLite database file.")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, db_path: str | None, verbose: bool) -> None:
    """Track office attendance against a quarterly target.

    :param ctx: the Click context, used to share the session factory with
        subcommands.
    :type ctx: click.Context
    :param db_path: path to the SQLite database file, or ``None`` to use
        the default (see :data:`attendance.db.DEFAULT_DB_PATH`).
    :type db_path: str | None
    :param verbose: enable debug-level logging to stderr.
    :type verbose: bool
    """
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "WARNING")

    ctx.ensure_object(dict)
    from .db import DEFAULT_DB_PATH

    ctx.obj["session_factory"] = get_session_factory(db_path or DEFAULT_DB_PATH)


@main.command()
@click.argument("day")
@click.argument("status", type=click.Choice(DayStatus.choices()))
@click.option("--note", default=None, help="Optional free-text note.")
@click.pass_context
def log(ctx: click.Context, day: str, status: str, note: str | None) -> None:
    """Log a day, e.g. `attendance log today office` or `attendance log 2026-09-15 leave`."""
    d = _parse_date(day)
    session_factory = ctx.obj["session_factory"]
    with session_factory() as session:
        try:
            row = upsert_day(session, d, DayStatus(status), note)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"Logged {row.day.isoformat()} as {row.status}" + (f" ({note})" if note else ""))


@main.command()
@click.argument("day")
@click.pass_context
def unlog(ctx: click.Context, day: str) -> None:
    """Remove a logged day."""
    d = _parse_date(day)
    session_factory = ctx.obj["session_factory"]
    with session_factory() as session:
        removed = delete_day(session, d)
    click.echo(f"Removed {d.isoformat()}" if removed else f"No entry for {d.isoformat()}")


@main.command()
@click.option("--quarter", default=None, help="e.g. 2026-Q3. Defaults to the current quarter.")
@click.option("--start", default=None, help="YYYY-MM-DD, use with --end instead of --quarter.")
@click.option("--end", default=None, help="YYYY-MM-DD, use with --start instead of --quarter.")
@click.option("--as-of", "as_of", default=None, help="YYYY-MM-DD or 'today'. Defaults to today.")
@click.option("--target", default=DEFAULT_TARGET_PCT, show_default=True, help="Target percentage.")
@click.pass_context
def stats(ctx: click.Context, quarter: str | None, start: str | None, end: str | None, as_of: str | None, target: float) -> None:
    """Show attendance percentage and progress toward the target."""
    period_start, period_end = _resolve_period(quarter, start, end)
    as_of_date = _parse_date(as_of) if as_of else None
    session_factory = ctx.obj["session_factory"]
    with session_factory() as session:
        s = compute_stats(session, period_start, period_end, as_of=as_of_date, target_pct=target)

    click.echo(f"Period:        {s.start.isoformat()} to {s.end.isoformat()} (as of {s.as_of.isoformat()})")
    click.echo(f"Office days:   {s.office_days}")
    click.echo(f"Remote days:   {s.remote_days}")
    click.echo(f"Leave days:    {s.leave_days}")
    click.echo(f"Holiday days:  {s.holiday_days}")
    click.echo(f"Working days counted (office+remote): {s.counted_days}")
    if s.percentage is None:
        click.echo("Attendance %:  n/a (no working days logged yet)")
    else:
        status = "ON TRACK" if s.on_track else "BEHIND"
        click.echo(f"Attendance %:  {s.percentage:.1f}% (target {s.target_pct:.0f}%) — {status}")
    if s.unlogged_weekdays:
        click.echo(f"\nUnlogged weekdays ({len(s.unlogged_weekdays)}) not counted in the above:")
        for d in s.unlogged_weekdays:
            click.echo(f"  - {d.isoformat()}")
    if s.remaining_weekdays:
        needed = s.office_days_needed
        click.echo(f"\nRemaining weekdays in period: {s.remaining_weekdays}")
        if needed is not None:
            achievable = "achievable" if s.target_achievable else "NOT achievable even attending every remaining day"
            click.echo(f"Office days needed to hit target: {needed} ({achievable})")


@main.command(name="list")
@click.option("--quarter", default=None, help="e.g. 2026-Q3. Defaults to the current quarter.")
@click.option("--start", default=None, help="YYYY-MM-DD, use with --end instead of --quarter.")
@click.option("--end", default=None, help="YYYY-MM-DD, use with --start instead of --quarter.")
@click.pass_context
def list_cmd(ctx: click.Context, quarter: str | None, start: str | None, end: str | None) -> None:
    """List logged days in a period."""
    period_start, period_end = _resolve_period(quarter, start, end)
    session_factory = ctx.obj["session_factory"]
    with session_factory() as session:
        rows = list_days(session, period_start, period_end)
    if not rows:
        click.echo("No logged days in this period.")
        return
    for row in rows:
        note = f"  ({row.note})" if row.note else ""
        click.echo(f"{row.day.isoformat()}  {row.status}{note}")


if __name__ == "__main__":
    main()
