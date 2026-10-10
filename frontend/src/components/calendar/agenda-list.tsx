'use client';

import { format, isToday } from 'date-fns';
import { CalendarEntryCard } from '@/components/calendar/calendar-entry-card';
import { dayKey } from '@/lib/calendar-range';
import type { CalendarEntry } from '@/types/schedule';

interface AgendaListProps {
  days: Date[];
  timeZone: string;
  byDay: Map<string, CalendarEntry[]>;
  /** Shown inside the list when none of the days has an entry ('' shows nothing, e.g. while loading). */
  emptyText: string;
  onEditLegacy?: (entry: CalendarEntry) => void;
  onDeleteLegacy?: (entry: CalendarEntry) => void;
  onReschedule?: (entry: CalendarEntry) => void;
  onCancelPlan?: (entry: CalendarEntry) => void;
}

/** The days that have entries, each with its entries as full cards; a compact note when there are none. */
export function AgendaList({ days, timeZone, byDay, emptyText, onEditLegacy, onDeleteLegacy, onReschedule, onCancelPlan }: AgendaListProps) {
  const withEntries = days.filter((day) => (byDay.get(dayKey(day)) ?? []).length > 0);
  if (withEntries.length === 0) {
    if (!emptyText) return null;
    return (
      <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground" data-testid="agenda-empty">
        {emptyText}
      </p>
    );
  }
  return (
    <div className="space-y-4" data-testid="agenda-list">
      {withEntries.map((day) => (
        <section key={dayKey(day)} aria-label={format(day, 'EEEE d MMMM yyyy')}>
          <h4 className={`mb-2 text-sm font-semibold ${isToday(day) ? 'text-primary' : 'text-foreground'}`}>
            {format(day, 'EEE d MMM')}{isToday(day) ? ' · Today' : ''}
          </h4>
          <div className="space-y-2">
            {byDay.get(dayKey(day))!.map((entry) => (
              <CalendarEntryCard key={entry.id} entry={entry} timeZone={timeZone}
                                 onEditLegacy={onEditLegacy} onDeleteLegacy={onDeleteLegacy}
                                 onReschedule={onReschedule} onCancelPlan={onCancelPlan} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
