const quarterSelect = document.getElementById("quarter-select");
const asOfInput = document.getElementById("as-of-input");
const targetInput = document.getElementById("target-input");
const daysBody = document.getElementById("days-body");
const errorBanner = document.getElementById("error-banner");

const STATUSES = ["office", "remote", "leave", "holiday"];

function todayIso() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

function quarterOf(date) {
  return Math.floor(date.getUTCMonth() / 3) + 1;
}

function quarterLabel(year, q) {
  return `${year}-Q${q}`;
}

function shiftQuarter(year, q, delta) {
  const zeroBased = (year * 4 + (q - 1)) + delta;
  return [Math.floor(zeroBased / 4), (zeroBased % 4) + 1];
}

function populateQuarterOptions() {
  const now = new Date();
  const curYear = now.getUTCFullYear();
  const curQ = quarterOf(now);
  quarterSelect.innerHTML = "";
  for (let delta = -2; delta <= 2; delta++) {
    const [y, q] = shiftQuarter(curYear, curQ, delta);
    const label = quarterLabel(y, q);
    const opt = document.createElement("option");
    opt.value = label;
    opt.textContent = label + (delta === 0 ? " (current)" : "");
    if (delta === 0) opt.selected = true;
    quarterSelect.appendChild(opt);
  }
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.add("visible");
  clearTimeout(showError._t);
  showError._t = setTimeout(() => errorBanner.classList.remove("visible"), 4000);
}

function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

function renderStats(stats) {
  document.getElementById("stat-pct-value").textContent = fmtPct(stats.percentage);
  document.getElementById("stat-office").textContent = stats.office_days;
  document.getElementById("stat-remote").textContent = stats.remote_days;
  document.getElementById("stat-leave").textContent = stats.leave_days;
  document.getElementById("stat-holiday").textContent = stats.holiday_days;

  const badge = document.getElementById("stat-badge");
  if (stats.on_track === null || stats.on_track === undefined) {
    badge.textContent = "";
    badge.className = "stat-badge";
  } else if (stats.on_track) {
    badge.textContent = "On track";
    badge.className = "stat-badge on-track";
  } else {
    badge.textContent = "Behind";
    badge.className = "stat-badge behind";
  }

  const projectionEl = document.getElementById("projection-text");
  if (stats.remaining_weekdays === 0) {
    projectionEl.textContent = "No working days remain in this period.";
  } else if (stats.office_days_needed === null || stats.office_days_needed === undefined) {
    projectionEl.textContent = `${stats.remaining_weekdays} weekday(s) remaining in this period.`;
  } else {
    const achievable = stats.target_achievable
      ? "achievable"
      : "NOT achievable even attending every remaining day";
    projectionEl.textContent =
      `${stats.remaining_weekdays} weekday(s) remaining — need ${stats.office_days_needed} more office day(s) ` +
      `to hit ${stats.target_pct}% (${achievable}).`;
  }
}

function weekdaysBetween(start, end) {
  const days = [];
  const cur = new Date(start);
  const last = new Date(end);
  while (cur <= last) {
    const dow = cur.getUTCDay();
    if (dow !== 0 && dow !== 6) days.push(isoDate(cur));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return days;
}

function statusClass(status) {
  return `status-select status-${status || "unlogged"}`;
}

async function setDayStatus(day, status, note) {
  if (!status) {
    await api(`/days/${day}`, { method: "DELETE" }).catch((err) => {
      if (!String(err.message).includes("not found")) throw err;
    });
    return;
  }
  await api(`/days/${day}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ day, status, note: note || null }),
  });
}

function renderDaysTable(weekdays, loggedByDay, asOf, today) {
  daysBody.innerHTML = "";
  const frag = document.createDocumentFragment();
  for (const day of weekdays) {
    const entry = loggedByDay.get(day);
    const tr = document.createElement("tr");
    if (day === today) tr.classList.add("today");
    if (day > asOf) tr.classList.add("future");

    const dateTd = document.createElement("td");
    dateTd.textContent = day;
    tr.appendChild(dateTd);

    const dowTd = document.createElement("td");
    dowTd.textContent = new Date(day).toLocaleDateString("en-US", {
      weekday: "short",
      timeZone: "UTC",
    });
    tr.appendChild(dowTd);

    const statusTd = document.createElement("td");
    const select = document.createElement("select");
    select.className = statusClass(entry && entry.status);
    const blankOpt = document.createElement("option");
    blankOpt.value = "";
    blankOpt.textContent = "— unlogged —";
    select.appendChild(blankOpt);
    for (const s of STATUSES) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s[0].toUpperCase() + s.slice(1);
      select.appendChild(opt);
    }
    select.value = entry ? entry.status : "";
    statusTd.appendChild(select);
    tr.appendChild(statusTd);

    const noteTd = document.createElement("td");
    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.className = "note-input";
    noteInput.placeholder = "note";
    noteInput.value = entry && entry.note ? entry.note : "";
    noteTd.appendChild(noteInput);
    tr.appendChild(noteTd);

    select.addEventListener("change", async () => {
      select.className = statusClass(select.value);
      try {
        await setDayStatus(day, select.value || null, noteInput.value);
        await refresh();
      } catch (err) {
        showError(err.message);
      }
    });

    noteInput.addEventListener("change", async () => {
      if (!select.value) return;
      try {
        await setDayStatus(day, select.value, noteInput.value);
      } catch (err) {
        showError(err.message);
      }
    });

    frag.appendChild(tr);
  }
  daysBody.appendChild(frag);
}

async function refresh() {
  try {
    const quarter = quarterSelect.value;
    const asOf = asOfInput.value || todayIso();
    const target = Number(targetInput.value) || 60;

    const [period, stats] = await Promise.all([
      api(`/period?quarter=${encodeURIComponent(quarter)}`),
      api(
        `/stats?quarter=${encodeURIComponent(quarter)}&as_of=${asOf}&target=${target}`
      ),
    ]);
    renderStats(stats);

    const days = await api(`/days?start=${period.start}&end=${period.end}`);
    const loggedByDay = new Map(days.map((d) => [d.day, d]));
    const weekdays = weekdaysBetween(period.start, period.end);
    renderDaysTable(weekdays, loggedByDay, asOf, todayIso());
  } catch (err) {
    showError(err.message);
  }
}

document.querySelectorAll(".quick-log-buttons .btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const status = btn.dataset.status;
    const statusEl = document.getElementById("quick-log-status");
    try {
      await setDayStatus(todayIso(), status, null);
      statusEl.textContent = `Logged today as ${status}.`;
      await refresh();
    } catch (err) {
      showError(err.message);
    }
  });
});

quarterSelect.addEventListener("change", refresh);
asOfInput.addEventListener("change", refresh);
targetInput.addEventListener("change", refresh);

populateQuarterOptions();
asOfInput.value = todayIso();
refresh();
