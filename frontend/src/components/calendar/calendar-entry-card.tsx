'use client';

import Link from 'next/link';
import { AlertTriangle, CalendarClock, CalendarX, Clock, Edit2, Link as LinkIcon, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatInstant } from '@/lib/calendar-time';
import type { CalendarConditionValue, CalendarEntry } from '@/types/schedule';

// Derived display conditions (from the server). They describe the entry; they never change its stored status,
// and none of them means the post was published — MCF does not publish.
const CONDITION_INFO: Record<string, { label: string; description: string }> = {
  date_passed: {
    label: 'Date passed',
    description: 'The planned time has passed. MCF does not publish posts, so this is not a record of publication.',
  },
  post_missing: { label: 'Post missing', description: 'The planned post no longer exists in this project.' },
  post_changed: {
    label: 'Post changed',
    description: 'The post changed after it was planned: the planned version or content no longer matches.',
  },
  product_mismatch: {
    label: 'Product mismatch',
    description: "This entry's product does not match its project's product.",
  },
};

export function conditionInfo(condition: CalendarConditionValue) {
  return CONDITION_INFO[condition] ?? { label: condition.replace(/_/g, ' '), description: condition.replace(/_/g, ' ') };
}

const STATUS_STYLES: Record<string, string> = {
  planned: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  cancelled: 'border-slate-400/40 bg-slate-500/10 text-slate-600 dark:text-slate-300 line-through decoration-1',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_STYLES[status] ?? 'border-border bg-muted text-foreground/80'}`}
      title={`Stored status: ${status}`}
    >
      <span className="sr-only">Status: </span>
      {status}
    </span>
  );
}

function ConditionBadge({ condition }: { condition: CalendarConditionValue }) {
  const info = conditionInfo(condition);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:text-amber-300"
      title={info.description}
    >
      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
      {info.label}
      <span className="sr-only">: {info.description}</span>
    </span>
  );
}

interface CalendarEntryCardProps {
  entry: CalendarEntry;
  /** The display zone (the browser's). */
  timeZone: string;
  /** Month grid cells use a compact card. */
  compact?: boolean;
  /** Legacy entries only: edit / delete through the legacy dialog. Planned entries are view-only. */
  onEditLegacy?: (entry: CalendarEntry) => void;
  onDeleteLegacy?: (entry: CalendarEntry) => void;
  /** Planned (non-legacy, not cancelled) entries only. */
  onReschedule?: (entry: CalendarEntry) => void;
  onCancelPlan?: (entry: CalendarEntry) => void;
}

export function CalendarEntryCard({ entry, timeZone, compact = false, onEditLegacy, onDeleteLegacy, onReschedule, onCancelPlan }: CalendarEntryCardProps) {
  const time = formatInstant(entry.scheduledAt, timeZone, { hour: '2-digit', minute: '2-digit' });
  const plannedZoneTime = entry.timezone && entry.timezone !== timeZone
    ? formatInstant(entry.scheduledAt, entry.timezone, { hour: '2-digit', minute: '2-digit' })
    : null;
  const cancelled = entry.status === 'cancelled' || entry.cancelledAt !== null;
  // Planning actions exist only for active planned entries; legacy entries keep their legacy actions.
  const plannedActions = !entry.isLegacy && !cancelled;
  const subtitle = [entry.productName, entry.contentType].filter(Boolean).join(' · ');
  const label = `${entry.projectTitle}, ${time}, ${entry.platform}, status ${entry.status}${entry.isLegacy ? ', legacy entry' : ''}`;

  return (
    <article
      aria-label={label}
      className={`group relative rounded-lg border bg-white dark:bg-card shadow-sm ${compact ? 'p-1.5 text-[11px]' : 'p-3 text-sm'} ${cancelled ? 'opacity-70' : ''}`}
    >
      <div className="flex items-start gap-2">
        <span className={`flex shrink-0 items-center gap-1 font-semibold tabular-nums text-foreground/80 ${compact ? 'text-[10px]' : 'text-xs'}`}>
          <Clock className="h-3 w-3 opacity-70" aria-hidden="true" />
          <time dateTime={entry.scheduledAt}>{time}</time>
        </span>
        <div className="min-w-0 flex-1">
          <p className={`truncate font-semibold text-foreground ${compact ? '' : 'text-sm'}`} title={entry.projectTitle}>
            {entry.projectTitle}
          </p>
          {subtitle && !compact && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
          {plannedZoneTime && !compact && (
            <p className="text-[11px] text-muted-foreground">Planned for {plannedZoneTime} ({entry.timezone})</p>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <span className="inline-flex items-center rounded-md border border-border px-1.5 py-0.5 text-[10px] font-medium text-foreground/80">
          <span className="sr-only">Platform: </span>
          {entry.platform}
        </span>
        <StatusBadge status={entry.status} />
        {entry.isLegacy && (
          <span
            className="inline-flex items-center rounded-md border border-dashed border-border px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="Created before content planning; it is not linked to a saved post version."
          >
            Legacy
          </span>
        )}
        {entry.conditions.map((condition) => (
          <ConditionBadge key={condition} condition={condition} />
        ))}
      </div>

      {!compact && entry.notes && <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">{entry.notes}</p>}
      {!compact && !entry.isLegacy && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Planned post, approved version {entry.contentVersion ?? '—'}.{cancelled ? ' This plan is cancelled and kept for history.' : ''}
        </p>
      )}

      {/* Compact cards: the toolbar stays in the layout (so its buttons are keyboard-focusable) and appears on hover or
          focus; on touch screens (no hover) it is always shown. While invisible it does not catch clicks. */}
      <div data-testid="entry-actions"
           className={`flex flex-wrap items-center gap-1 ${compact ? 'absolute right-1 top-1 rounded-md border bg-white p-0.5 shadow-md dark:bg-card pointer-events-none opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100' : 'mt-2'}`}>
        <Button asChild variant="ghost" size="icon" className="h-6 w-6">
          <Link href={`/projects/${entry.projectId}`} aria-label={`Open project ${entry.projectTitle}`} title="Open project">
            <LinkIcon className="h-3 w-3" aria-hidden="true" />
          </Link>
        </Button>
        {entry.isLegacy && onEditLegacy && (
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onEditLegacy(entry)}
                  aria-label={`Edit legacy entry for ${entry.projectTitle}`} title="Edit legacy entry">
            <Edit2 className="h-3 w-3" aria-hidden="true" />
          </Button>
        )}
        {entry.isLegacy && onDeleteLegacy && (
          <Button variant="ghost" size="icon" className="h-6 w-6 hover:text-destructive" onClick={() => onDeleteLegacy(entry)}
                  aria-label={`Delete legacy entry for ${entry.projectTitle}`} title="Delete legacy entry">
            <Trash2 className="h-3 w-3" aria-hidden="true" />
          </Button>
        )}
        {plannedActions && onReschedule && (compact ? (
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onReschedule(entry)}
                  aria-label={`Reschedule plan for ${entry.projectTitle}`} title="Reschedule">
            <CalendarClock className="h-3 w-3" aria-hidden="true" />
          </Button>
        ) : (
          <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => onReschedule(entry)}
                  aria-label={`Reschedule plan for ${entry.projectTitle}`}>
            <CalendarClock className="mr-1 h-3 w-3" aria-hidden="true" />Reschedule
          </Button>
        ))}
        {plannedActions && onCancelPlan && (compact ? (
          <Button variant="ghost" size="icon" className="h-6 w-6 hover:text-destructive" onClick={() => onCancelPlan(entry)}
                  aria-label={`Cancel plan for ${entry.projectTitle}`} title="Cancel plan">
            <CalendarX className="h-3 w-3" aria-hidden="true" />
          </Button>
        ) : (
          <Button variant="outline" size="sm" className="h-7 px-2 text-xs hover:text-destructive" onClick={() => onCancelPlan(entry)}
                  aria-label={`Cancel plan for ${entry.projectTitle}`}>
            <CalendarX className="mr-1 h-3 w-3" aria-hidden="true" />Cancel plan
          </Button>
        ))}
      </div>
    </article>
  );
}
