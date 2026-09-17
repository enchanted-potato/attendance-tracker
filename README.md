# Attendance Tracker

Tracks office attendance against a quarterly target (default **60%** of
working days) and tells you where you stand as of any given date.

- **Working days** = Mon-Fri, excluding public holidays and annual leave.
- Each working day you log as one of: `office`, `remote`, `leave`, `holiday`.
- The percentage is `office days / (office days + remote days)`, i.e.
  `leave` and `holiday` days are removed from the denominator entirely.
- Weekends are never logged — they're derived from the date automatically.
- Quarters are calendar quarters (Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep,
  Q4 Oct-Dec).

Data is stored in a local SQLite file (default `~/.attendance-tracker/attendance.db`,
override with the `ATTENDANCE_DB` env var or `attendance --db PATH`).

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI usage

```bash
# Log days (status: office | remote | leave | holiday)
attendance log 2026-09-15 office
attendance log 2026-09-16 remote
attendance log 2026-09-17 leave --note "doctor's appointment"
attendance log today office

# Remove a logged day
attendance unlog 2026-09-16

# See your stats for the current quarter, as of today
attendance stats

# As of a specific date, or a specific/custom quarter
attendance stats --as-of 2026-08-31
attendance stats --quarter 2026-Q3
attendance stats --start 2026-07-01 --end 2026-09-30

# List everything logged in a period
attendance list --quarter 2026-Q3
```

Example output:

```
Period:        2026-07-01 to 2026-09-30 (as of 2026-09-17)
Office days:   32
Remote days:   18
Leave days:    3
Holiday days:  1
Working days counted (office+remote): 50
Attendance %:  64.0% (target 60%) — ON TRACK

Remaining weekdays in period: 9
Office days needed to hit target: 2 (achievable)
```

Any weekday in the queried range that hasn't been logged yet is listed
separately as "unlogged" — it's excluded from the percentage rather than
silently guessed, so gaps in your logging never quietly skew the number.

`office_days_needed` / `target_achievable` project forward: assuming every
remaining weekday in the period turns out to be a working day, how many of
them you'd need to spend in the office to still hit the target by the end
of the quarter.

## API usage

```bash
uvicorn attendance.api:app --reload
```

- `PUT /days/{day}` — body `{"day": "2026-09-15", "status": "office", "note": null}`
- `GET /days/{day}`
- `DELETE /days/{day}`
- `GET /days?start=2026-07-01&end=2026-09-30`
- `GET /stats?quarter=2026-Q3&as_of=2026-09-17&target=60`
  (or `?start=...&end=...` instead of `quarter`)

Interactive docs at `http://127.0.0.1:8000/docs` once running.

## Tests

```bash
pytest
```
