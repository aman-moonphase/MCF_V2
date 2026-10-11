'use client';

// The signed-in user's preferences, loaded once and shared (module cache). Screens that only *use* preferences
// (Calendar, Add to Calendar) fall back to the defaults when they cannot be loaded; the Settings page shows errors.
import { useEffect, useSyncExternalStore } from 'react';
import { DEFAULT_SETTINGS, SettingsService, type UserSettings } from '@/lib/services/settings.service';

type State = { status: 'loading' | 'ready' | 'error'; settings: UserSettings };

let state: State = { status: 'loading', settings: DEFAULT_SETTINGS };
let inFlight: Promise<void> | null = null;
// The cache belongs to one signed-in user: a different token (log out / log in) means reload.
let loadedForToken: string | null | undefined;
let generation = 0;  // only the latest request may update the cache

function currentToken(): string | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage.getItem('access_token');
  } catch {
    return null;
  }
}
const listeners = new Set<() => void>();

function set(next: State) {
  state = next;
  listeners.forEach((listener) => listener());
}

function load(force = false): Promise<void> {
  const token = currentToken();
  if (token !== loadedForToken) {
    force = true;
    if (state.status !== 'loading') set({ status: 'loading', settings: DEFAULT_SETTINGS });
  }
  if (inFlight && !force) return inFlight;
  if (state.status === 'ready' && !force) return Promise.resolve();
  loadedForToken = token;
  const mine = ++generation;
  const request = SettingsService.get()
    .then((settings) => { if (mine === generation) set({ status: 'ready', settings }); })
    .catch(() => { if (mine === generation) set({ status: 'error', settings: DEFAULT_SETTINGS }); })
    .finally(() => { if (inFlight === request) inFlight = null; });
  inFlight = request;
  return request;
}

/** After the server confirmed a save: every screen uses the stored values. */
export function setCachedUserSettings(settings: UserSettings) {
  generation += 1;  // a confirmed save supersedes any load still in flight
  loadedForToken = currentToken();
  set({ status: 'ready', settings });
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const SERVER_STATE: State = { status: 'loading', settings: DEFAULT_SETTINGS };

/** { status, settings } — defaults until loaded (and on error). */
export function useUserSettings(): State {
  const current = useSyncExternalStore(subscribe, () => state, () => SERVER_STATE);
  useEffect(() => {
    void load();
  }, []);
  return current;
}

export function reloadUserSettings(): Promise<void> {
  return load(true);
}
