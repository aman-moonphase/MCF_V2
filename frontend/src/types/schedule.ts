export interface Schedule {
  id: string;
  projectId: string;
  platform: string;
  scheduledAt: string; // ISO date string
  status: 'Draft' | 'Approved' | 'Scheduled' | 'Completed' | 'planned' | 'cancelled';
  createdAt: string;
  updatedAt: string;
  // Content planning fields (null for legacy entries; returned by the backend since planning was added)
  productId?: string | null;
  generatedContentId?: string | null;
  contentVersion?: number | null;
  contentDigest?: string | null;
  contentType?: string | null;
  timezone?: string | null;
  notes?: string | null;
  lockVersion?: number;
  cancelledAt?: string | null;
}

export interface ScheduleWithProject extends Schedule {
  projectTitle: string;
}

export interface CreateScheduleRequest {
  projectId: string;
  platform: string;
  scheduledAt: string;
  status?: string;
}

export interface UpdateScheduleRequest {
  platform?: string;
  scheduledAt?: string;
  status?: string;
}

// ─── Content planning (backend: app/schemas/schedule.py) ───────────────────
// Planning is not publishing: no status here means a post was published.

/** Stored status of an entry planned for an approved post. */
export type PlanningStatus = 'planned' | 'cancelled';

/**
 * Status exactly as stored. Planned entries use PlanningStatus; legacy entries keep their original value
 * (e.g. 'Scheduled') and are never relabelled, so any other string is passed through unchanged.
 */
export type StoredScheduleStatus = PlanningStatus | (string & {});

/** Display conditions derived by the server (they never change the stored status). */
export type CalendarCondition =
  | 'date_passed'      // the entry's time has passed (not cancelled) — not "published"
  | 'post_missing'     // a planned entry's post no longer exists in its project
  | 'post_changed'     // the post's current version/content differs from the planned version/digest
  | 'product_mismatch'; // the entry's product differs from its project's product (or is not the user's)

/** Known conditions plus any the server adds later (kept as-is, never dropped). */
export type CalendarConditionValue = CalendarCondition | (string & {});

export const CALENDAR_CONDITIONS: readonly CalendarCondition[] = ['date_passed', 'post_missing', 'post_changed', 'product_mismatch'];

interface CalendarEntryBase {
  id: string;
  projectId: string;
  projectTitle: string;
  productId: string | null;
  productName: string | null;
  /** The stored UTC instant (ISO 8601). */
  scheduledAt: string;
  /** The same instant expressed in the requested display time zone (only when one was requested). */
  scheduledAtLocal: string | null;
  /** IANA zone the entry was planned in (null for legacy entries). */
  timezone: string | null;
  platform: string;
  notes: string | null;
  status: StoredScheduleStatus;
  contentType: string | null;
  lockVersion: number;
  cancelledAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  conditions: CalendarConditionValue[];
}

/** An entry that plans a specific saved post version. `generatedContentId` is null if the post was deleted. */
export interface PlannedCalendarEntry extends CalendarEntryBase {
  isLegacy: false;
  generatedContentId: string | null;
  contentVersion: number | null;
  contentDigest: string | null;
  /** The linked post now — null when it no longer exists in the project. */
  currentContentStatus: string | null;
  currentContentVersion: number | null;
}

/** Created before content planning: no post reference was ever recorded (and none is invented). */
export interface LegacyCalendarEntry extends CalendarEntryBase {
  isLegacy: true;
  generatedContentId: null;
  contentVersion: null;
  contentDigest: null;
  currentContentStatus: null;
  currentContentVersion: null;
}

export type CalendarEntry = PlannedCalendarEntry | LegacyCalendarEntry;

/** Query for GET /schedules/calendar — the half-open range [start, end). */
export interface CalendarQuery {
  /** Inclusive start. A Date, or an ISO 8601 string WITH an offset ('Z' or ±hh:mm). */
  start: Date | string;
  /** Exclusive end. Same rules as `start`. */
  end: Date | string;
  productId?: string;
  includeCancelled?: boolean;
  /** IANA zone for `scheduledAtLocal` (display only; never inferred from the server). */
  timezone?: string;
}

/** GET /schedules/calendar response: the echoed query plus the entries, oldest first. */
export interface CalendarRangeResponse {
  start: string;
  end: string;
  timezone: string | null;
  productId: string | null;
  includeCancelled: boolean;
  entries: CalendarEntry[];
}

/** Why a calendar request failed. */
export type CalendarErrorKind =
  | 'auth'             // 401/403: sign in again
  | 'validation'       // 422 from the server, or an invalid query caught before sending
  | 'not_found'        // 404: e.g. a product filter that is not the user's
  | 'network'          // the request did not reach the server
  | 'server'           // any other HTTP error
  | 'invalid_response'; // the response did not match the contract

// ─── Planning an approved post (backend: PlanContentRequest / PlanEligibilityResponse / ScheduleResponse) ─────

/** A server refusal, passed through unchanged (e.g. not_approved, evaluation_missing, duplicate_plan, time_in_past). */
export interface PlanningRefusal {
  code: string;
  message: string;
}

/** GET /projects/{id}/generated-content/schedule/eligibility */
export interface PlanEligibility {
  eligible: boolean;
  reasons: PlanningRefusal[];
  projectId: string | null;
  productId: string | null;
  generatedContentId: string | null;
  contentType: string | null;
  platform: string | null;
  contentVersion: number | null;
  evaluationId: string | null;
}

/** POST /projects/{id}/generated-content/schedule — the status is always "planned" and is not sent. */
export interface PlanPostRequest {
  /** ISO 8601 with the chosen zone's real offset on that date. */
  scheduledAt: string;
  /** IANA zone the time was chosen in. */
  timezone: string;
  platform: string;
  notes?: string;
  /** Expected product; the server refuses if the project belongs to another. */
  productId?: string;
}

/** The created entry (ScheduleResponse). */
export interface PlannedEntry {
  id: string;
  projectId: string;
  productId: string | null;
  generatedContentId: string | null;
  contentVersion: number | null;
  contentType: string | null;
  platform: string;
  scheduledAt: string;
  timezone: string | null;
  notes: string | null;
  status: StoredScheduleStatus;
  lockVersion: number;
  cancelledAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** PATCH /schedules/{id} — only planning fields; `lockVersion` must be the entry's current value. */
export interface ReschedulePlanRequest {
  lockVersion: number;
  /** ISO 8601 with the zone's real offset on that date (send together with `timezone`). */
  scheduledAt?: string;
  timezone?: string;
  /** A string sets the notes; null clears them; omit to keep them. */
  notes?: string | null;
}

/** Why planning failed. */
export type PlanningErrorKind =
  | 'auth'        // 401/403
  | 'not_found'   // 404: not your project (or it does not exist)
  | 'refused'     // 409: an eligibility refusal or a duplicate plan
  | 'validation'  // 422: time, time zone or platform (or a local check before sending)
  | 'network'     // never reached the server
  | 'server';     // anything else
