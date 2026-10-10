'use client';

import { format, isSameMonth, isToday } from 'date-fns';
import { Plus } from 'lucide-react';
import { CalendarEntryCard } from '@/components/calendar/calendar-entry-card';
import { dayKey } from '@/lib/calendar-range';
import type { CalendarEntry } from '@/types/schedule';

const WEEKDAYS = [
  { short: 'S', label: 'Sun', name: 'Sunday' },
  { short: 'M', label: 'Mon', name: 'Monday' },
  { short: 'T', label: 'Tue', name: 'Tuesday' },
  { short: 'W', label: 'Wed', name: 'Wednesday' },
  { short: 'T', label: 'Thu', name: 'Thursday' },
  { short: 'F', label: 'Fri', name: 'Friday' },
  { short: 'S', label: 'Sat', name: 'Saturday' },
];
const MAX_DOTS = 3;

// Narrow-screen dots: a cancelled plan (shown with "Show cancelled") must not look like an active one.
type DotKind = 'cancelled' | 'attention' | 'active';
const DOT_STYLES: Record<DotKind, string> = {
  cancelled: 'border border-muted-foreground/60 bg-transparent',
  attention: 'bg-amber-500',
  active: 'bg-primary',
};
function dotKind(entry: CalendarEntry): DotKind {
  if (entry.status === 'cancelled' || entry.cancelledAt !== null) return 'cancelled';
  return entry.conditions.length ? 'attention' : 'active';
}

interface MonthGridProps {
  /** Every local day of the grid (whole weeks), from calendarRange('month', anchor). */
  days: Date[];
  /** Any moment in the displayed month; days of other months are muted. */
  anchor: Date;
  timeZone: string;
  /** Entries grouped by local day key (yyyy-MM-dd). An empty map still renders every date. */
  byDay: Map<string, CalendarEntry[]>;
  onSelectDay: (day: Date) => void;
  onAddLegacy?: (day: Date) => void;
  onEditLegacy?: (entry: CalendarEntry) => void;
  onDeleteLegacy?: (entry: CalendarEntry) => void;
  onReschedule?: (entry: CalendarEntry) => void;
  onCancelPlan?: (entry: CalendarEntry) => void;
}

/**
 * The month as a seven-column grid at every width. Narrow screens get compact cells (date + entry dots; tapping a
 * date opens that day); wider screens also show the entries inside each cell.
 */
export function MonthGrid({ days, anchor, timeZone, byDay, onSelectDay, onAddLegacy, onEditLegacy, onDeleteLegacy, onReschedule, onCancelPlan }: MonthGridProps) {
  return (
    <div className="grid grid-cols-7 gap-1 md:gap-2" data-testid="month-grid">
      {WEEKDAYS.map((d) => (
        <div key={d.name} className="py-1 text-center text-[11px] font-medium text-muted-foreground md:text-xs">
          <span aria-hidden="true" className="md:hidden">{d.short}</span>
          <span aria-hidden="true" className="hidden md:inline">{d.label}</span>
          <span className="sr-only">{d.name}</span>
        </div>
      ))}
      {days.map((day) => {
        const key = dayKey(day);
        const entries = byDay.get(key) ?? [];
        const outside = !isSameMonth(day, anchor);
        const today = isToday(day);
        const count = entries.length;
        const label = `${format(day, 'EEEE d MMMM yyyy')}${count ? `, ${count} ${count === 1 ? 'entry' : 'entries'}` : ', nothing planned'}`;
        return (
          <div
            key={key}
            data-day={key}
            data-outside={outside ? 'true' : 'false'}
            className={`group/cell flex min-h-12 flex-col rounded-lg border p-1 md:min-h-32 md:rounded-xl md:p-1.5 ${today ? 'border-primary/40 bg-primary/5' : 'border-slate-200 dark:border-border bg-white dark:bg-card'} ${outside ? 'opacity-50' : ''}`}
          >
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => onSelectDay(day)}
                aria-label={label}
                aria-current={today ? 'date' : undefined}
                className={`flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold md:h-6 md:w-6 md:text-xs md:font-bold ${today ? 'bg-primary text-primary-foreground' : outside ? 'text-muted-foreground hover:bg-muted' : 'text-foreground hover:bg-muted'}`}
              >
                {format(day, 'd')}
              </button>
              {onAddLegacy && (
                <button
                  type="button"
                  onClick={() => onAddLegacy(day)}
                  aria-label={`Add a legacy entry on ${format(day, 'd MMMM yyyy')}`}
                  className="hidden rounded p-0.5 text-muted-foreground opacity-0 hover:bg-muted hover:text-foreground focus:opacity-100 group-hover/cell:opacity-100 md:block"
                >
                  <Plus className="h-3 w-3" aria-hidden="true" />
                </button>
              )}
            </div>

            {/* Narrow screens: dots only (the day's entries are listed below the grid). */}
            {count > 0 && (
              <div className="mt-0.5 flex items-center justify-center gap-0.5 md:hidden" aria-hidden="true">
                {entries.slice(0, MAX_DOTS).map((entry) => (
                  <span key={entry.id} data-dot={dotKind(entry)} className={`h-1.5 w-1.5 rounded-full ${DOT_STYLES[dotKind(entry)]}`} />
                ))}
                {count > MAX_DOTS && <span className="text-[9px] leading-none text-muted-foreground">+{count - MAX_DOTS}</span>}
              </div>
            )}

            {/* Wider screens: the entries themselves. */}
            {count > 0 && (
              <div className="mt-1 hidden max-h-40 flex-col gap-1 overflow-y-auto md:flex">
                {entries.map((entry) => (
                  <CalendarEntryCard key={entry.id} entry={entry} compact timeZone={timeZone}
                                     onEditLegacy={onEditLegacy} onDeleteLegacy={onDeleteLegacy}
                                     onReschedule={onReschedule} onCancelPlan={onCancelPlan} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
