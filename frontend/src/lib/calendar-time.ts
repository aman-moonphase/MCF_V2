// Time helpers for the calendar data layer.
//
// - Instants are exchanged as ISO 8601 strings WITH an explicit offset ('Z' or ±hh:mm). A string without an
//   offset is rejected rather than guessed, and the server's clock or zone is never used.
// - Ranges are half-open: [start, end).
// - Display conversion never changes the instant: formatting in another IANA zone only changes how it is shown.

/** ISO 8601 date-time with seconds optional and a mandatory offset. */
const OFFSET_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/;

export class InstantError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InstantError';
  }
}

export function hasExplicitOffset(value: string): boolean {
  return OFFSET_ISO.test(value) && !Number.isNaN(Date.parse(value));
}

/**
 * The query value for an instant. A Date becomes its exact UTC instant ('…Z'); a string must already carry an
 * offset and is sent unchanged (the caller's offset is preserved).
 */
export function toInstantParam(value: Date | string, name = 'time'): string {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) throw new InstantError(`'${name}' is not a valid date.`);
    return value.toISOString();
  }
  if (typeof value !== 'string' || !hasExplicitOffset(value)) {
    throw new InstantError(`'${name}' must be an ISO 8601 time with an offset, e.g. 2026-11-01T00:00:00+05:30.`);
  }
  return value;
}

/** Milliseconds since the epoch for an instant (Date or offset-bearing ISO string). */
export function instantMs(value: Date | string, name = 'time'): number {
  return Date.parse(toInstantParam(value, name));
}

/** Half-open membership: start <= instant < end. */
export function isWithinRange(instant: Date | string, start: Date | string, end: Date | string): boolean {
  const t = instantMs(instant, 'instant');
  return instantMs(start, 'start') <= t && t < instantMs(end, 'end');
}

/** Whether the runtime knows this IANA zone (the server re-validates it). */
export function isSupportedTimeZone(timeZone: string): boolean {
  if (!timeZone || timeZone !== timeZone.trim()) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone });
    return true;
  } catch {
    return false;
  }
}

/** Show an instant in an IANA zone without changing it. */
export function formatInstant(
  instant: Date | string,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
  locale?: string,
): string {
  return new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(new Date(instantMs(instant, 'instant')));
}

// ─── Wall-clock time in a named zone → exact instant ───────────────────────

const DATE_INPUT = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIME_INPUT = /^(\d{2}):(\d{2})$/;
const HOUR_MS = 3600000;

/** UTC offset (ms) of an IANA zone at an instant, from the runtime's time-zone data. */
export function zoneOffsetMs(timeZone: string, instantMs: number): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(new Date(instantMs));
  const n = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const wallAsUtc = Date.UTC(n('year'), n('month') - 1, n('day'), n('hour') % 24, n('minute'), n('second'));
  return wallAsUtc - Math.floor(instantMs / 1000) * 1000;
}

/** "+05:30" / "-04:00" / "+00:00" for an offset in ms. */
export function formatOffset(offsetMs: number): string {
  const sign = offsetMs < 0 ? '-' : '+';
  const minutes = Math.abs(Math.round(offsetMs / 60000));
  return `${sign}${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

export interface ZonedTime {
  /** ISO 8601 with the zone's real offset on that date, e.g. "2027-05-04T10:30:00+05:30". */
  iso: string;
  instantMs: number;
  offset: string;
  /** The wall-clock time happens twice that day (clocks went back); the first occurrence is used. */
  ambiguous: boolean;
}

/**
 * The instant at which the clock in `timeZone` shows `date` (yyyy-MM-dd) `time` (HH:mm). The offset is looked up
 * for that date (daylight saving included). A time that does not exist in the zone (clocks went forward) throws.
 */
export function zonedDateTimeToIso(date: string, time: string, timeZone: string): ZonedTime {
  const d = DATE_INPUT.exec(date);
  const t = TIME_INPUT.exec(time);
  if (!d) throw new InstantError('Choose a date.');
  if (!t) throw new InstantError('Choose a time.');
  if (!isSupportedTimeZone(timeZone)) throw new InstantError(`"${timeZone}" is not a valid IANA time zone.`);
  const [year, month, day, hour, minute] = [Number(d[1]), Number(d[2]), Number(d[3]), Number(t[1]), Number(t[2])];
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  const check = new Date(wall);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || hour > 23 || minute > 59) {
    throw new InstantError('That date or time does not exist.');
  }
  // Offsets in force around that wall time; an offset is valid when the zone really has it at the resulting instant.
  const candidates = [...new Set([zoneOffsetMs(timeZone, wall - 12 * HOUR_MS), zoneOffsetMs(timeZone, wall),
                                  zoneOffsetMs(timeZone, wall + 12 * HOUR_MS)])];
  const valid = candidates
    .map((offset) => ({ offset, instantMs: wall - offset }))
    .filter(({ offset, instantMs }) => zoneOffsetMs(timeZone, instantMs) === offset)
    .sort((a, b) => a.instantMs - b.instantMs);
  if (valid.length === 0) {
    throw new InstantError(`${time} does not exist on ${date} in ${timeZone} (the clocks go forward). Choose another time.`);
  }
  const { offset, instantMs } = valid[0];
  return { iso: `${date}T${time}:00${formatOffset(offset)}`, instantMs, offset: formatOffset(offset), ambiguous: valid.length > 1 };
}

/** The wall-clock date (yyyy-MM-dd) and time (HH:mm) of an instant in an IANA zone — e.g. to prefill inputs. */
export function zonedParts(instant: Date | string, timeZone: string): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).formatToParts(new Date(instantMs(instant, 'instant')));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return { date: `${get('year')}-${get('month')}-${get('day')}`, time: `${get('hour')}:${get('minute')}` };
}

/** IANA zones known to the runtime (for suggestions); the chosen zone is still validated by the server. */
export function knownTimeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    return intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : [];
  } catch {
    return [];
  }
}
