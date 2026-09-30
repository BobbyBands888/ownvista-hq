// America/New_York helpers (DST-safe, no dependencies).

export const TZ = 'America/New_York';

const fmt = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
});

// Wall-clock parts in New York for a given instant.
export function et(date = new Date()) {
  const p = Object.fromEntries(fmt.formatToParts(date).map((x) => [x.type, x.value]));
  const weekdays = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return {
    year: +p.year, month: +p.month, day: +p.day,
    hour: +p.hour, minute: +p.minute, weekday: weekdays[p.weekday],
    date: `${p.year}-${p.month}-${p.day}`,
  };
}

export function etDate(date = new Date()) {
  return et(date).date;
}

// The UTC instant for a New York wall-clock time (handles DST by checking the offset).
export function etToUtc(dateStr, hour = 0, minute = 0) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const target = Date.UTC(y, m - 1, d, hour, minute);
  const offsetAt = (ms) => {
    const w = et(new Date(ms));
    return Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute) - ms;
  };
  let t = target - offsetAt(target);
  t = target - offsetAt(t);
  return new Date(t);
}

export function addDays(dateStr, n) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function daysAgoIso(n) {
  return new Date(Date.now() - n * 86400000).toISOString();
}
