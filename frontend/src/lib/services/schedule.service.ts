import { apiClient } from '../api-client';
import { isApiResponseError } from '../api-errors';
import { hasExplicitOffset, InstantError, instantMs, isSupportedTimeZone, toInstantParam } from '../calendar-time';
import type {
  Schedule,
  ScheduleWithProject,
  CreateScheduleRequest,
  UpdateScheduleRequest,
  CalendarEntry,
  CalendarErrorKind,
  CalendarQuery,
  CalendarRangeResponse,
  PlanEligibility,
  PlannedEntry,
  PlanningErrorKind,
  PlanningRefusal,
  PlanPostRequest,
  ReschedulePlanRequest,
} from '@/types/schedule';

/** A failed calendar request, classified so callers can react predictably. */
export class CalendarApiError extends Error {
  readonly kind: CalendarErrorKind;
  readonly status?: number;

  constructor(kind: CalendarErrorKind, message: string, status?: number) {
    super(message);
    this.name = 'CalendarApiError';
    this.kind = kind;
    this.status = status;
  }
}

/**
 * Query parameters for GET /schedules/calendar, serialized with URLSearchParams (so '+05:30' is sent as '%2B05:30').
 * Validates what can be checked locally; the server remains authoritative.
 */
export function buildCalendarParams(query: CalendarQuery): URLSearchParams {
  let start: string;
  let end: string;
  try {
    start = toInstantParam(query.start, 'start');
    end = toInstantParam(query.end, 'end');
  } catch (e) {
    throw new CalendarApiError('validation', e instanceof InstantError ? e.message : 'Invalid calendar range.');
  }
  if (instantMs(start) >= instantMs(end)) {
    throw new CalendarApiError('validation', "'start' must be before 'end' (the range is [start, end)).");
  }
  if (query.timezone !== undefined && !isSupportedTimeZone(query.timezone)) {
    throw new CalendarApiError('validation', "'timezone' must be a valid IANA time zone, e.g. Asia/Kolkata.");
  }
  const params = new URLSearchParams({ start, end });
  if (query.productId) params.set('product_id', query.productId);
  if (query.includeCancelled !== undefined) params.set('include_cancelled', query.includeCancelled ? 'true' : 'false');
  if (query.timezone) params.set('timezone', query.timezone);
  return params;
}

function toCalendarError(error: unknown): CalendarApiError {
  if (error instanceof CalendarApiError) return error;
  if (isApiResponseError(error)) {
    const kind: CalendarErrorKind =
      error.status === 401 || error.status === 403 ? 'auth'
      : error.status === 422 ? 'validation'
      : error.status === 404 ? 'not_found'
      : 'server';
    return new CalendarApiError(kind, error.message, error.status);
  }
  // fetch() rejects with a TypeError when the request never reached the server.
  if (error instanceof TypeError) {
    return new CalendarApiError('network', 'Could not reach the server. Check your connection and try again.');
  }
  return new CalendarApiError('server', error instanceof Error ? error.message : 'The calendar could not be loaded.');
}

const isStr = (v: unknown): v is string => typeof v === 'string';
const isOptStr = (v: unknown) => v === null || v === undefined || typeof v === 'string';
const isOptNum = (v: unknown) => v === null || v === undefined || typeof v === 'number';

function invalid(why: string): CalendarApiError {
  return new CalendarApiError('invalid_response', `Unexpected calendar response: ${why}.`);
}

function checkEntry(raw: unknown, index: number): CalendarEntry {
  const e = raw as Record<string, unknown>;
  if (!e || typeof e !== 'object') throw invalid(`entry ${index} is not an object`);
  for (const key of ['id', 'projectId', 'projectTitle', 'scheduledAt', 'platform', 'status'] as const) {
    if (!isStr(e[key])) throw invalid(`entry ${index} has no ${key}`);
  }
  if (typeof e.isLegacy !== 'boolean') throw invalid(`entry ${index} has no isLegacy flag`);
  if (!Array.isArray(e.conditions) || !e.conditions.every(isStr)) throw invalid(`entry ${index} has invalid conditions`);
  if (typeof e.lockVersion !== 'number') throw invalid(`entry ${index} has no lockVersion`);
  for (const key of ['productId', 'productName', 'scheduledAtLocal', 'timezone', 'notes', 'contentType', 'generatedContentId',
    'contentDigest', 'currentContentStatus', 'cancelledAt', 'createdAt', 'updatedAt'] as const) {
    if (!isOptStr(e[key])) throw invalid(`entry ${index} has an invalid ${key}`);
  }
  for (const key of ['contentVersion', 'currentContentVersion'] as const) {
    if (!isOptNum(e[key])) throw invalid(`entry ${index} has an invalid ${key}`);
  }
  if (e.isLegacy && (e.generatedContentId != null || e.contentVersion != null || e.contentDigest != null)) {
    throw invalid(`legacy entry ${index} has a post reference`);
  }
  // Values are passed through unchanged (stored status, conditions); only absent optionals become null.
  const nullIfMissing = <T,>(v: T | undefined) => (v === undefined ? null : v);
  return {
    ...e,
    productId: nullIfMissing(e.productId), productName: nullIfMissing(e.productName),
    scheduledAtLocal: nullIfMissing(e.scheduledAtLocal), timezone: nullIfMissing(e.timezone), notes: nullIfMissing(e.notes),
    contentType: nullIfMissing(e.contentType), generatedContentId: nullIfMissing(e.generatedContentId),
    contentVersion: nullIfMissing(e.contentVersion), contentDigest: nullIfMissing(e.contentDigest),
    currentContentStatus: nullIfMissing(e.currentContentStatus), currentContentVersion: nullIfMissing(e.currentContentVersion),
    cancelledAt: nullIfMissing(e.cancelledAt), createdAt: nullIfMissing(e.createdAt), updatedAt: nullIfMissing(e.updatedAt),
  } as CalendarEntry;
}

/** Checks the (camelCased) response against the backend contract (app/schemas/schedule.py::CalendarResponse). */
export function parseCalendarResponse(raw: unknown): CalendarRangeResponse {
  const r = raw as Record<string, unknown>;
  if (!r || typeof r !== 'object') throw invalid('not an object');
  if (!isStr(r.start) || !isStr(r.end)) throw invalid('missing start/end');
  if (!isOptStr(r.timezone) || !isOptStr(r.productId)) throw invalid('invalid filters');
  if (typeof r.includeCancelled !== 'boolean') throw invalid('missing includeCancelled');
  if (!Array.isArray(r.entries)) throw invalid('missing entries');
  return {
    start: r.start,
    end: r.end,
    timezone: (r.timezone as string | null | undefined) ?? null,
    productId: (r.productId as string | null | undefined) ?? null,
    includeCancelled: r.includeCancelled,
    entries: r.entries.map(checkEntry),
  };
}

/** A failed planning request: the kind, and the server's refusal reasons exactly as returned. */
export class PlanningApiError extends Error {
  readonly kind: PlanningErrorKind;
  readonly status?: number;
  readonly reasons: PlanningRefusal[];
  /** On a lock_conflict: the entry's current lock_version on the server. */
  readonly currentLockVersion?: number;

  constructor(kind: PlanningErrorKind, message: string, reasons: PlanningRefusal[] = [], status?: number, currentLockVersion?: number) {
    super(message);
    this.name = 'PlanningApiError';
    this.kind = kind;
    this.reasons = reasons;
    this.status = status;
    this.currentLockVersion = currentLockVersion;
  }

  hasCode(code: string): boolean {
    return this.reasons.some((r) => r.code === code);
  }
}

function refusalsFrom(detail: unknown): PlanningRefusal[] {
  const reasons = (detail as { reasons?: unknown } | null)?.reasons;
  if (!Array.isArray(reasons)) return [];
  return reasons.filter((r): r is PlanningRefusal => !!r && typeof r.code === 'string' && typeof r.message === 'string');
}

function toPlanningError(error: unknown): PlanningApiError {
  if (error instanceof PlanningApiError) return error;
  if (isApiResponseError(error)) {
    const kind: PlanningErrorKind =
      error.status === 401 || error.status === 403 ? 'auth'
      : error.status === 404 ? 'not_found'
      : error.status === 409 ? 'refused'
      : error.status === 422 ? 'validation'
      : 'server';
    const lockVersion = (error.detail as { lock_version?: unknown } | null)?.lock_version;
    return new PlanningApiError(kind, error.message, refusalsFrom(error.detail), error.status,
                                typeof lockVersion === 'number' ? lockVersion : undefined);
  }
  if (error instanceof TypeError) {
    return new PlanningApiError('network', 'Could not reach the server. Nothing was saved — check your connection and try again.');
  }
  return new PlanningApiError('server', error instanceof Error ? error.message : 'The request failed. Nothing was saved.');
}

const planUrl = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/generated-content/schedule`;
const entryUrl = (scheduleId: string) => `/schedules/${encodeURIComponent(scheduleId)}`;

export const ScheduleService = {
  /** The latest stored state of one of your entries (e.g. after a lock_conflict). Throws PlanningApiError. */
  async getPlan(scheduleId: string): Promise<PlannedEntry> {
    try {
      return await apiClient.get(entryUrl(scheduleId));
    } catch (error) {
      throw toPlanningError(error);
    }
  },

  /**
   * Reschedule a planned entry: time / time zone / notes only, with the entry's current lock_version. The server
   * re-checks eligibility and that the planned post is unchanged. Throws PlanningApiError (lock_conflict carries the
   * server's currentLockVersion) — a failure never means anything was changed.
   */
  async reschedulePlan(scheduleId: string, request: ReschedulePlanRequest): Promise<PlannedEntry> {
    if (!Number.isInteger(request.lockVersion) || request.lockVersion < 1) {
      throw new PlanningApiError('validation', 'The entry version is missing. Reload the calendar and try again.');
    }
    if ((request.scheduledAt === undefined) !== (request.timezone === undefined)) {
      throw new PlanningApiError('validation', 'Send the planned time together with its time zone.');
    }
    if (request.scheduledAt !== undefined && !hasExplicitOffset(request.scheduledAt)) {
      throw new PlanningApiError('validation', 'The planned time must include its UTC offset.');
    }
    const body: Record<string, unknown> = { lockVersion: request.lockVersion };
    if (request.scheduledAt !== undefined) {
      body.scheduledAt = request.scheduledAt;
      body.timezone = request.timezone;
    }
    if (request.notes !== undefined) body.notes = request.notes === null ? null : request.notes.trim() || null;
    try {
      return await apiClient.patch(entryUrl(scheduleId), body);
    } catch (error) {
      throw toPlanningError(error);
    }
  },

  /** Cancel a planned entry (kept in history, never deleted), with its current lock_version. Throws PlanningApiError. */
  async cancelPlan(scheduleId: string, lockVersion: number): Promise<PlannedEntry> {
    if (!Number.isInteger(lockVersion) || lockVersion < 1) {
      throw new PlanningApiError('validation', 'The entry version is missing. Reload the calendar and try again.');
    }
    try {
      return await apiClient.post(`${entryUrl(scheduleId)}/cancel`, { lockVersion });
    } catch (error) {
      throw toPlanningError(error);
    }
  },

  /** Read-only: whether the project's saved post can be planned now, and why not. Throws PlanningApiError. */
  async getPlanEligibility(projectId: string): Promise<PlanEligibility> {
    try {
      return await apiClient.get(`${planUrl(projectId)}/eligibility`);
    } catch (error) {
      throw toPlanningError(error);
    }
  },

  /**
   * Plan the project's approved, evaluated post (status "planned"; nothing is published). The server re-checks
   * every eligibility rule. Throws PlanningApiError — a failure never means a plan was saved.
   */
  async planPost(projectId: string, request: PlanPostRequest): Promise<PlannedEntry> {
    if (!hasExplicitOffset(request.scheduledAt)) {
      throw new PlanningApiError('validation', 'The planned time must include its UTC offset.');
    }
    const body: Record<string, string> = { scheduledAt: request.scheduledAt, timezone: request.timezone, platform: request.platform };
    if (request.notes?.trim()) body.notes = request.notes.trim();
    if (request.productId) body.productId = request.productId;
    try {
      return await apiClient.post(planUrl(projectId), body);
    } catch (error) {
      throw toPlanningError(error);
    }
  },

  async getSchedules(): Promise<ScheduleWithProject[]> {
    return apiClient.get('/schedules');
  },

  /**
   * Calendar entries whose instant is in [start, end), oldest first, with derived display conditions.
   * Throws CalendarApiError (kind: auth | validation | not_found | network | server | invalid_response).
   */
  async getCalendar(query: CalendarQuery): Promise<CalendarRangeResponse> {
    const params = buildCalendarParams(query);
    let raw: unknown;
    try {
      raw = await apiClient.get(`/schedules/calendar?${params.toString()}`);
    } catch (error) {
      throw toCalendarError(error);
    }
    return parseCalendarResponse(raw);
  },

  async getSchedule(id: string): Promise<Schedule> {
    return apiClient.get(`/schedules/${id}`);
  },

  async createSchedule(data: CreateScheduleRequest): Promise<Schedule> {
    return apiClient.post('/schedules', data);
  },

  async updateSchedule(id: string, data: UpdateScheduleRequest): Promise<Schedule> {
    return apiClient.put(`/schedules/${id}`, data);
  },

  async deleteSchedule(id: string): Promise<boolean> {
    return apiClient.delete(`/schedules/${id}`);
  },
};
