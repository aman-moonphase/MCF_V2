'use client';

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { format, isToday } from 'date-fns';
import { ChevronLeft, ChevronRight, Plus, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CalendarEntryCard } from '@/components/calendar/calendar-entry-card';
import { AgendaList } from '@/components/calendar/agenda-list';
import { MonthGrid } from '@/components/calendar/month-grid';
import { RescheduleDialog, describePlanTime } from '@/components/calendar/reschedule-plan-dialog';
import { CancelPlanDialog } from '@/components/calendar/cancel-plan-dialog';
import { ScheduleDialog } from './schedule-dialog';
import { CalendarApiError, ScheduleService } from '@/lib/services/schedule.service';
import { ProductService, type Product } from '@/lib/services/product.service';
import { useUserSettings } from '@/lib/use-user-settings';
import {
  CALENDAR_VIEWS,
  type CalendarViewMode,
  calendarRange,
  dayKey,
  instantDayKey,
  localTimeZone,
  rangeLabel,
  shiftAnchor,
} from '@/lib/calendar-range';
import type { CalendarEntry, CalendarRangeResponse, ScheduleWithProject } from '@/types/schedule';

const ALL_PRODUCTS = 'all';

// Browser-only values: null while rendering on the server, so nothing is ever derived from the server's clock or zone.
const noSubscription = () => () => {};
let firstClientNow: Date | null = null;
const clientNow = () => (firstClientNow ??= new Date());
function useBrowserValue<T>(read: () => T): T | null {
  return useSyncExternalStore(noSubscription, read, () => null);
}

interface CalendarResult {
  key: string | null;
  data: CalendarRangeResponse | null;
  error: CalendarApiError | null;
}

/** The legacy dialog edits legacy entries through the legacy route; it takes the legacy list shape. */
function toLegacySchedule(entry: CalendarEntry): ScheduleWithProject {
  return {
    id: entry.id, projectId: entry.projectId, projectTitle: entry.projectTitle, platform: entry.platform,
    scheduledAt: entry.scheduledAt, status: entry.status as ScheduleWithProject['status'],
    createdAt: entry.createdAt ?? '', updatedAt: entry.updatedAt ?? '',
  };
}

function errorText(error: CalendarApiError): string {
  switch (error.kind) {
    case 'auth': return 'Your session has expired. Sign in again to see your calendar.';
    case 'network': return 'Could not reach the server. Check your connection and try again.';
    case 'not_found': return 'The selected product was not found. Choose another product or show all products.';
    case 'validation': return `The calendar range could not be loaded: ${error.message}`;
    case 'invalid_response': return 'The server sent an unexpected calendar response. Try again.';
    default: return `The calendar could not be loaded: ${error.message}`;
  }
}

export function CalendarView() {
  // The display zone and "today" come from the browser — never from the server.
  const timeZone = useBrowserValue(localTimeZone);
  const today = useBrowserValue(clientNow);
  const [chosenAnchor, setAnchor] = useState<Date | null>(null);
  const anchor = chosenAnchor ?? today;
  // Opens in the user's saved default view (Settings) until a view is chosen here.
  const preferences = useUserSettings();
  const [chosenView, setView] = useState<CalendarViewMode | null>(null);
  const view: CalendarViewMode = chosenView ?? preferences.settings.calendarDefaultView;
  const [productId, setProductId] = useState<string>(ALL_PRODUCTS);
  const [includeCancelled, setIncludeCancelled] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);

  const [result, setResult] = useState<CalendarResult>({ key: null, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);

  // Legacy dialog (legacy entries only).
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [selectedSchedule, setSelectedSchedule] = useState<ScheduleWithProject | undefined>(undefined);
  const [initialDate, setInitialDate] = useState<string | undefined>(undefined);
  // Planned entries: reschedule / cancel (one dialog at a time, for one entry).
  const [planAction, setPlanAction] = useState<{ kind: 'reschedule' | 'cancel'; entry: CalendarEntry } | null>(null);

  useEffect(() => {
    ProductService.list().then(setProducts).catch(() => setProducts([]));  // the filter is optional
  }, []);

  const range = useMemo(() => (anchor ? calendarRange(view, anchor) : null), [view, anchor]);
  const label = anchor ? rangeLabel(view, anchor) : '';

  // One key per request; a response is shown only if it belongs to the current key (late responses are ignored).
  const requestKey = range && timeZone && preferences.status !== 'loading'  // no Month fetch before a saved Week/Day view
    ? JSON.stringify([range.start.getTime(), range.end.getTime(), timeZone, productId, includeCancelled, reloadKey])
    : null;
  useEffect(() => {
    if (!requestKey || !range || !timeZone) return;
    let current = true;
    ScheduleService.getCalendar({
      start: range.start, end: range.end, timezone: timeZone, includeCancelled,
      productId: productId === ALL_PRODUCTS ? undefined : productId,
    })
      .then((data) => {
        if (current) setResult({ key: requestKey, data, error: null });
      })
      .catch((e: unknown) => {
        if (current) {
          setResult({ key: requestKey, data: null, error: e instanceof CalendarApiError ? e : new CalendarApiError('server', 'The calendar could not be loaded.') });
        }
      });
    return () => {
      current = false;
    };
  }, [requestKey, range, timeZone, productId, includeCancelled]);

  const loading = result.key !== requestKey;
  const data = result.data;  // while a new range loads, the previous one stays visible (dimmed)
  const error = loading ? null : result.error;

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const byDay = useMemo(() => {
    const groups = new Map<string, CalendarEntry[]>();
    if (!data || !timeZone) return groups;
    for (const entry of data.entries) {
      const key = instantDayKey(entry.scheduledAt, timeZone);
      groups.set(key, [...(groups.get(key) ?? []), entry]);
    }
    return groups;
  }, [data, timeZone]);

  const entries = data?.entries ?? [];
  // A compact note inside the calendar (never a panel that hides the dates).
  const showEmptyNote = !loading && !error && data !== null && entries.length === 0;
  const emptyText = `Nothing planned for ${label}.${includeCancelled ? '' : ' Cancelled entries are hidden.'}`;

  const openNewLegacyEntry = (day?: Date) => {
    setInitialDate(day ? dayKey(day) : undefined);
    setSelectedSchedule(undefined);
    setIsDialogOpen(true);
  };

  const editLegacy = (entry: CalendarEntry) => {
    if (!entry.isLegacy) return;  // planned entries are view-only here
    setSelectedSchedule(toLegacySchedule(entry));
    setIsDialogOpen(true);
  };

  const deleteLegacy = async (entry: CalendarEntry) => {
    if (!entry.isLegacy) return;
    if (!confirm(`Delete this legacy calendar entry for "${entry.projectTitle}"? This only removes the calendar entry.`)) return;
    try {
      await ScheduleService.deleteSchedule(entry.id);
      toast.success('Legacy calendar entry deleted');
      reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to delete the calendar entry');
    }
  };

  const goToDay = (day: Date) => {
    setAnchor(day);
    setView('day');
  };

  const openPlanAction = (kind: 'reschedule' | 'cancel') => (entry: CalendarEntry) => {
    if (entry.isLegacy || entry.status === 'cancelled' || entry.cancelledAt !== null) return;  // planned, active only
    setPlanAction({ kind, entry });
  };

  const cardProps = {
    timeZone: timeZone ?? 'UTC', onEditLegacy: editLegacy, onDeleteLegacy: deleteLegacy,
    onReschedule: openPlanAction('reschedule'), onCancelPlan: openPlanAction('cancel'),
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col gap-1">
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight text-foreground">Content Calendar</h2>
        <p className="text-muted-foreground">
          Plan when approved content goes out. MCF records plans only — nothing is published automatically.
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Calendar view" className="inline-flex rounded-lg border border-slate-200 dark:border-border bg-white dark:bg-card p-1 shadow-sm">
            {CALENDAR_VIEWS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={view === option.value}
                onClick={() => setView(option.value)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${view === option.value ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-border bg-white dark:bg-card p-1 shadow-sm">
            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Previous ${view}`}
                    onClick={() => anchor && setAnchor(shiftAnchor(view, anchor, -1))} disabled={!anchor}>
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button variant="ghost" size="sm" className="h-8" onClick={() => setAnchor(new Date())}>Today</Button>
            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Next ${view}`}
                    onClick={() => anchor && setAnchor(shiftAnchor(view, anchor, 1))} disabled={!anchor}>
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          <h3 className="text-lg font-bold text-foreground" aria-live="polite">{label}</h3>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {products.length > 0 && (
            <div className="w-48">
              <Select value={productId} onValueChange={setProductId}>
                <SelectTrigger aria-label="Filter by product" className="h-9">
                  <SelectValue placeholder="All products" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_PRODUCTS}>All products</SelectItem>
                  {products.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" className="h-4 w-4 accent-primary" checked={includeCancelled}
                   onChange={(e) => setIncludeCancelled(e.target.checked)} />
            Show cancelled
          </label>
          <Button variant="outline" size="sm" onClick={() => openNewLegacyEntry(anchor ?? undefined)}>
            <Plus className="mr-1 h-4 w-4" aria-hidden="true" /> Legacy entry
          </Button>
        </div>
      </div>
      {timeZone && <p className="-mt-3 text-xs text-muted-foreground">Times are shown in your time zone: {timeZone}.</p>}

      {/* Status */}
      {loading && (
        <div role="status" className="text-sm text-muted-foreground animate-pulse">Loading calendar…</div>
      )}
      {error && !loading && (
        <Card role="alert" className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-foreground">{errorText(error)}</p>
            <div className="flex gap-2">
              {error.kind === 'auth' ? (
                <Button asChild size="sm"><Link href="/login">Sign in</Link></Button>
              ) : (
                <Button size="sm" variant="outline" onClick={reload}>
                  <RefreshCw className="mr-1 h-4 w-4" aria-hidden="true" /> Retry
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      {range && anchor && (
        <div className={loading ? 'opacity-60 transition-opacity' : 'transition-opacity'} aria-busy={loading}>
          {/* Month: the date grid at every width — it never depends on there being entries. */}
          {view === 'month' && (
            <div className="space-y-4">
              <MonthGrid days={range.days} anchor={anchor} byDay={byDay} onSelectDay={goToDay}
                         onAddLegacy={openNewLegacyEntry} {...cardProps} />
              {showEmptyNote && <p className="text-center text-sm text-muted-foreground" data-testid="calendar-empty-note">{emptyText}</p>}
              {/* Narrow screens: the month's entries as a list under the compact grid. */}
              {entries.length > 0 && (
                <div className="md:hidden">
                  <AgendaList days={range.days} byDay={byDay} emptyText={emptyText} {...cardProps} />
                </div>
              )}
            </div>
          )}

          {/* Week and Day on narrow screens: an agenda list (with a compact note when empty). */}
          {view !== 'month' && (
            <div className="md:hidden">
              <AgendaList days={range.days} byDay={byDay} emptyText={showEmptyNote ? emptyText : ''} {...cardProps} />
            </div>
          )}

          {view === 'week' && (
            <div className="hidden md:block">
              <div className="grid grid-cols-7 gap-2">
                {range.days.map((day) => {
                  const dayEntries = byDay.get(dayKey(day)) ?? [];
                  return (
                    <section key={dayKey(day)} aria-label={format(day, 'EEEE d MMMM')}
                             className={`flex min-h-64 flex-col rounded-xl border p-2 ${isToday(day) ? 'border-primary/40 bg-primary/5' : 'border-slate-200 dark:border-border bg-white dark:bg-card'}`}>
                      <button type="button" onClick={() => goToDay(day)} className="mb-2 text-left text-xs font-semibold text-muted-foreground hover:text-foreground">
                        {format(day, 'EEE d')}{isToday(day) ? ' · Today' : ''}
                      </button>
                      <div className="flex flex-col gap-2">
                        {dayEntries.map((entry) => <CalendarEntryCard key={entry.id} entry={entry} compact {...cardProps} />)}
                      </div>
                    </section>
                  );
                })}
              </div>
              {showEmptyNote && <p className="mt-3 text-center text-sm text-muted-foreground">{emptyText}</p>}
            </div>
          )}

          {view === 'day' && (
            <div className="mx-auto hidden max-w-2xl space-y-2 md:block">
              {entries.map((entry) => <CalendarEntryCard key={entry.id} entry={entry} {...cardProps} />)}
              {showEmptyNote && (
                <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">{emptyText}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Planned entries: reschedule / cancel. The calendar reloads after a confirmed change or a detected conflict. */}
      {planAction?.kind === 'reschedule' && (
        <RescheduleDialog
          key={`reschedule-${planAction.entry.id}`}
          entry={planAction.entry}
          open
          onOpenChange={(next) => { if (!next) setPlanAction(null); }}
          onRescheduled={(updated) => {
            toast.success(`Plan moved to ${describePlanTime(updated.scheduledAt, updated.timezone ?? timeZone ?? 'UTC')}. Nothing has been published.`);
            reload();
          }}
          onStale={reload}
        />
      )}
      {planAction?.kind === 'cancel' && (
        <CancelPlanDialog
          key={`cancel-${planAction.entry.id}`}
          entry={planAction.entry}
          open
          onOpenChange={(next) => { if (!next) setPlanAction(null); }}
          onCancelled={() => {
            toast.success('Plan cancelled. It stays in the calendar history; nothing was published or deleted.');
            reload();
          }}
          onStale={reload}
        />
      )}

      {/* Legacy dialog: legacy-compatible projects and legacy entries only. */}
      <ScheduleDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onScheduled={reload}
        existingSchedule={selectedSchedule}
        initialDate={initialDate}
      />
    </div>
  );
}
