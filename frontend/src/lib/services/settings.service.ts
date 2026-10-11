import { apiClient } from '../api-client';
import { isApiResponseError } from '../api-errors';

export type CalendarDefaultView = 'month' | 'week' | 'day';

/** Your preferences (backend: GET/PUT /api/settings/me). `saved` is false while defaults are in use. */
export interface UserSettings {
  /** IANA zone used by default for new plans; null = your browser's zone. */
  timezone: string | null;
  calendarDefaultView: CalendarDefaultView;
  /** HH:MM, 24-hour. */
  defaultPlanTime: string;
  saved: boolean;
  updatedAt: string | null;
}

export type UserSettingsInput = Pick<UserSettings, 'timezone' | 'calendarDefaultView' | 'defaultPlanTime'>;

export const DEFAULT_SETTINGS: UserSettings = {
  timezone: null, calendarDefaultView: 'month', defaultPlanTime: '09:00', saved: false, updatedAt: null,
};

export type SettingsErrorKind = 'auth' | 'validation' | 'network' | 'server';

export class SettingsApiError extends Error {
  readonly kind: SettingsErrorKind;
  readonly status?: number;

  constructor(kind: SettingsErrorKind, message: string, status?: number) {
    super(message);
    this.name = 'SettingsApiError';
    this.kind = kind;
    this.status = status;
  }
}

function toSettingsError(error: unknown): SettingsApiError {
  if (isApiResponseError(error)) {
    const kind: SettingsErrorKind = error.status === 401 || error.status === 403 ? 'auth' : error.status === 422 ? 'validation' : 'server';
    return new SettingsApiError(kind, error.message, error.status);
  }
  if (error instanceof TypeError) return new SettingsApiError('network', 'Could not reach the server. Nothing was saved.');
  return new SettingsApiError('server', error instanceof Error ? error.message : 'The request failed.');
}

export const SettingsService = {
  async get(): Promise<UserSettings> {
    try {
      return await apiClient.get('/settings/me');
    } catch (error) {
      throw toSettingsError(error);
    }
  },

  /** Saves and returns what the server stored. Throws SettingsApiError — a failure means nothing was saved. */
  async save(input: UserSettingsInput): Promise<UserSettings> {
    try {
      return await apiClient.put('/settings/me', {
        timezone: input.timezone?.trim() ? input.timezone.trim() : null,
        calendarDefaultView: input.calendarDefaultView,
        defaultPlanTime: input.defaultPlanTime,
      });
    } catch (error) {
      throw toSettingsError(error);
    }
  },
};
