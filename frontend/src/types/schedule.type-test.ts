// Compile-time checks for the calendar types (run by `tsc --noEmit`; never imported by the app).
// A line marked @ts-expect-error must fail to compile; if it ever compiles, tsc reports the unused directive.
import type {
  CalendarCondition,
  CalendarEntry,
  CalendarQuery,
  CalendarRangeResponse,
  LegacyCalendarEntry,
  PlannedCalendarEntry,
  StoredScheduleStatus,
} from './schedule';

const base = {
  id: 's1', projectId: 'p1', projectTitle: 'Campaign', productId: null, productName: null,
  scheduledAt: '2026-11-03T03:30:00Z', scheduledAtLocal: null, timezone: null, platform: 'LinkedIn', notes: null,
  contentType: null, lockVersion: 1, cancelledAt: null, createdAt: null, updatedAt: null, conditions: [],
};

// Legacy entries carry no post reference.
export const legacy: LegacyCalendarEntry = {
  ...base, status: 'Scheduled', isLegacy: true, generatedContentId: null, contentVersion: null, contentDigest: null,
  currentContentStatus: null, currentContentVersion: null,
};
// @ts-expect-error a legacy entry cannot reference a post
export const legacyWithPost: LegacyCalendarEntry = { ...legacy, generatedContentId: 'g1' };

// Planned entries keep the planned version/digest and the post's current state separately.
export const planned: PlannedCalendarEntry = {
  ...base, status: 'planned', isLegacy: false, generatedContentId: 'g1', contentVersion: 1, contentDigest: 'a'.repeat(64),
  currentContentStatus: 'approved', currentContentVersion: 2, conditions: ['post_changed', 'date_passed'],
};

// Stored statuses pass through unchanged: planning values and any legacy value.
export const statuses: StoredScheduleStatus[] = ['planned', 'cancelled', 'Scheduled'];

// Narrowing on isLegacy gives the post fields their precise types.
export function plannedVersion(entry: CalendarEntry): number | null {
  if (entry.isLegacy) {
    const none: null = entry.contentVersion;
    return none;
  }
  return entry.contentVersion;
}

// Known conditions are a closed union; unknown future ones are still accepted on entries.
export const known: CalendarCondition[] = ['date_passed', 'post_missing', 'post_changed', 'product_mismatch'];
// @ts-expect-error "published" is not a calendar condition
export const notACondition: CalendarCondition = 'published';
export const future: CalendarEntry['conditions'] = ['date_passed', 'some_future_condition'];

// Queries take a Date or an ISO string; filters are optional.
export const query: CalendarQuery = { start: new Date(), end: '2026-12-01T00:00:00+05:30', timezone: 'Asia/Kolkata' };
// @ts-expect-error start is required
export const missingStart: CalendarQuery = { end: new Date() };

export const response: CalendarRangeResponse = {
  start: '2026-11-01T00:00:00Z', end: '2026-12-01T00:00:00Z', timezone: null, productId: null, includeCancelled: false,
  entries: [legacy, planned],
};
