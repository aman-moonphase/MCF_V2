// Calendar ranges for the Month / Week / Day views, in the browser's local time zone.
//
// Boundaries are local midnights computed with date-fns calendar arithmetic (addDays/addWeeks/addMonths keep the
// local wall-clock date), so a day that is 23 or 25 hours long because of a daylight-saving change is still exactly
// one calendar day. Each range is half-open, [start, end), and is sent to the API as exact instants.
import {
  addDays,
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from 'date-fns';

export type CalendarViewMode = 'month' | 'week' | 'day';

export const CALENDAR_VIEWS: { value: CalendarViewMode; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'week', label: 'Week' },
  { value: 'day', label: 'Day' },
];

/** Weeks start on Sunday, as in the existing calendar grid. */
export const WEEK_STARTS_ON = 0 as const;

export interface CalendarRange {
  view: CalendarViewMode;
  /** Inclusive local midnight. */
  start: Date;
  /** Exclusive local midnight (the first day NOT shown). */
  end: Date;
  /** Every local day shown, in order (whole weeks for the month grid). */
  days: Date[];
}

/** The range shown for `anchor` (any moment inside the period). */
export function calendarRange(view: CalendarViewMode, anchor: Date): CalendarRange {
  let start: Date;
  let end: Date;
  if (view === 'month') {
    // Whole weeks covering the month, so leading/trailing days in the grid show their entries too.
    start = startOfWeek(startOfMonth(anchor), { weekStartsOn: WEEK_STARTS_ON });
    end = addDays(startOfDay(endOfWeek(endOfMonth(anchor), { weekStartsOn: WEEK_STARTS_ON })), 1);
  } else if (view === 'week') {
    start = startOfWeek(anchor, { weekStartsOn: WEEK_STARTS_ON });
    end = addWeeks(start, 1);
  } else {
    start = startOfDay(anchor);
    end = addDays(start, 1);
  }
  return { view, start, end, days: eachDayOfInterval({ start, end: addDays(end, -1) }) };
}

/** The anchor one period earlier (-1) or later (+1). */
export function shiftAnchor(view: CalendarViewMode, anchor: Date, step: -1 | 1): Date {
  if (view === 'month') return addMonths(startOfMonth(anchor), step);
  if (view === 'week') return addWeeks(anchor, step);
  return addDays(anchor, step);
}

/** Heading for the displayed period, e.g. "October 2026", "4 – 10 Oct 2026", "Saturday, 10 October 2026". */
export function rangeLabel(view: CalendarViewMode, anchor: Date): string {
  if (view === 'month') return format(anchor, 'MMMM yyyy');
  if (view === 'day') return format(anchor, 'EEEE, d MMMM yyyy');
  const { start, end } = calendarRange('week', anchor);
  const last = addDays(end, -1);
  if (start.getFullYear() !== last.getFullYear()) return `${format(start, 'd MMM yyyy')} – ${format(last, 'd MMM yyyy')}`;
  if (start.getMonth() !== last.getMonth()) return `${format(start, 'd MMM')} – ${format(last, 'd MMM yyyy')}`;
  return `${format(start, 'd')} – ${format(last, 'd MMM yyyy')}`;
}

/** The browser's IANA time zone (never the server's). */
export function localTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Local calendar-day key (yyyy-MM-dd) of a Date in the browser's zone. */
export function dayKey(day: Date): string {
  return format(day, 'yyyy-MM-dd');
}

/** Local calendar-day key of an instant (ISO string with offset), in the given IANA zone. */
export function instantDayKey(instant: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date(Date.parse(instant)));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}
