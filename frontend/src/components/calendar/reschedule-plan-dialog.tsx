'use client';

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { AlertTriangle, CalendarCheck, Info, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  LONG_DATE_TIME, NOTES_MAX, dialogBody, dialogContent, dialogFooter, dialogHeader, inputField, sectionTitle,
} from '@/components/calendar/dialog-layout';
import { InstantError, formatInstant, isSupportedTimeZone, knownTimeZones, zonedDateTimeToIso, zonedParts } from '@/lib/calendar-time';
import { localTimeZone } from '@/lib/calendar-range';
import { PlanningApiError, ScheduleService } from '@/lib/services/schedule.service';
import type { CalendarEntry, PlannedEntry, PlanningRefusal } from '@/types/schedule';

// "Now" for the past-time hint, refreshed every 30 s (the server re-checks the time on save).
const CLOCK_MS = 30000;
const subscribeClock = (onChange: () => void) => {
  const id = setInterval(onChange, CLOCK_MS);
  return () => clearInterval(id);
};
const readClock = () => Math.floor(Date.now() / CLOCK_MS) * CLOCK_MS;

/** The stored values the form starts from (and the lock_version a save must carry). */
interface PlanState {
  lockVersion: number;
  scheduledAt: string;
  timezone: string;
  notes: string | null;
  status: string;
  cancelledAt: string | null;
}

const fromEntry = (e: Pick<PlannedEntry, 'lockVersion' | 'scheduledAt' | 'timezone' | 'notes' | 'status' | 'cancelledAt'>, fallbackZone: string): PlanState => ({
  lockVersion: e.lockVersion, scheduledAt: e.scheduledAt, timezone: e.timezone || fallbackZone, notes: e.notes,
  status: String(e.status), cancelledAt: e.cancelledAt,
});

export function describePlanTime(instant: string, timeZone: string): string {
  return `${formatInstant(instant, timeZone, LONG_DATE_TIME)} (${timeZone})`;
}

/** A clear message for a failed reschedule/cancel; never implies anything was changed. */
export function planningFailureMessage(error: PlanningApiError, action: 'reschedule' | 'cancel'): string {
  const what = action === 'reschedule' ? 'The plan was not rescheduled.' : 'The plan was not cancelled.';
  if (error.kind === 'auth') return `Your session has expired or you no longer have access. Sign in again. ${what}`;
  if (error.kind === 'not_found') return `This calendar entry is no longer available. ${what}`;
  if (error.kind === 'network') return `Could not reach the server. ${what} Check your connection and try again.`;
  if (error.hasCode('content_changed')) {
    return `The approved post changed after it was planned, so this plan cannot be rescheduled under the current rules. ${what} You can still cancel it and plan the current approved version.`;
  }
  if (error.hasCode('cancelled')) return `This plan is already cancelled. ${what}`;
  if (error.hasCode('legacy_entry')) return `This is a legacy calendar entry; use its legacy edit or delete actions instead. ${what}`;
  if (error.kind === 'refused') return `This plan cannot be ${action === 'reschedule' ? 'rescheduled' : 'cancelled'} right now. ${what}`;
  if (error.kind === 'validation') return `The new time is not valid. ${what}`;
  return `The server could not complete the request (${error.message}). ${what}`;
}

interface RescheduleDialogProps {
  entry: CalendarEntry;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The server confirmed the new time. */
  onRescheduled: (entry: PlannedEntry) => void;
  /** The stored entry differs from what was shown (conflict / cancelled elsewhere): refresh the calendar. */
  onStale: () => void;
}

/** Reschedule a planned entry: date, time, time zone and notes. The approved post and its version are unchanged. */
export function RescheduleDialog({ entry, open, onOpenChange, onRescheduled, onStale }: RescheduleDialogProps) {
  const browserZone = useSyncExternalStore(() => () => {}, localTimeZone, () => 'UTC');
  const [base, setBase] = useState<PlanState>(() => fromEntry(entry, browserZone));
  const initial = useMemo(() => ({ ...zonedParts(base.scheduledAt, base.timezone), timezone: base.timezone, notes: base.notes ?? '' }), [base]);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const [timeZone, setTimeZone] = useState(initial.timezone);
  const [notes, setNotes] = useState(initial.notes);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const [failure, setFailure] = useState<{ message: string; reasons: PlanningRefusal[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState<PlannedEntry | null>(null);
  const zones = useMemo(() => knownTimeZones(), []);
  const now = useSyncExternalStore(subscribeClock, readClock, () => 0);
  const messageRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (failure || notice) messageRef.current?.scrollIntoView({ block: 'nearest' });
  }, [failure, notice]);

  const cancelledNow = base.status === 'cancelled' || base.cancelledAt !== null;
  const timeChanged = date !== initial.date || time !== initial.time || timeZone !== initial.timezone;
  const notesChanged = notes.trim() !== (base.notes ?? '').trim();

  let preview: { text: string; iso: string; ambiguous: boolean } | null = null;
  let previewError: string | null = null;
  try {
    const zoned = zonedDateTimeToIso(date, time, timeZone);
    if (timeChanged && zoned.instantMs <= now) previewError = 'That time is in the past. Choose a future date and time.';
    else preview = { text: `${formatInstant(zoned.iso, timeZone, LONG_DATE_TIME)} in ${timeZone} (UTC${zoned.offset})`, iso: zoned.iso, ambiguous: zoned.ambiguous };
  } catch (e) {
    previewError = e instanceof InstantError ? e.message : 'That date or time is not valid.';
  }
  const canSave = !cancelledNow && !submitting && !!preview && (timeChanged || notesChanged);

  const close = (next: boolean) => {
    if (submitting) return;
    onOpenChange(next);
  };

  /** Reload the stored entry after a conflict, refill the form from it, and say so. Never overwrites. */
  const reloadLatest = async (reason: string) => {
    onStale();
    try {
      const latest = await ScheduleService.getPlan(entry.id);
      const next = fromEntry(latest, browserZone);
      setBase(next);
      const parts = zonedParts(next.scheduledAt, next.timezone);
      setDate(parts.date);
      setTime(parts.time);
      setTimeZone(next.timezone);
      setNotes(next.notes ?? '');
      const gone = next.status === 'cancelled' || next.cancelledAt !== null;
      setNotice(gone
        ? `${reason} It has since been cancelled, so it can no longer be rescheduled. Nothing was changed.`
        : `${reason} The latest details (planned for ${describePlanTime(next.scheduledAt, next.timezone)}) are shown below. Nothing was saved — review them and save again if you still want to change the plan.`);
    } catch (e) {
      const error = e instanceof PlanningApiError ? e : new PlanningApiError('server', 'Could not load the latest plan.');
      setNotice(null);
      setFailure({ message: planningFailureMessage(error, 'reschedule'), reasons: [] });
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlight.current || !canSave || !preview) return;  // one request at a time
    if (timeChanged && zonedDateTimeToIso(date, time, timeZone).instantMs <= Date.now()) {
      setFailure({ message: 'That time is in the past. Choose a future date and time. The plan was not rescheduled.', reasons: [] });
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    setFailure(null);
    setNotice(null);
    try {
      const updated = await ScheduleService.reschedulePlan(entry.id, {
        lockVersion: base.lockVersion,
        ...(timeChanged ? { scheduledAt: preview.iso, timezone: timeZone } : {}),
        ...(notesChanged ? { notes: notes.trim() || null } : {}),
      });
      setSaved(updated);
      onRescheduled(updated);
    } catch (e) {
      const error = e instanceof PlanningApiError ? e : new PlanningApiError('server', 'The request failed.');
      if (error.hasCode('lock_conflict') || error.hasCode('cancelled')) {
        await reloadLatest('This plan was changed somewhere else after you opened it.');
      } else {
        setFailure({ message: planningFailureMessage(error, 'reschedule'),
                     reasons: error.reasons.filter((r) => !['content_changed', 'cancelled', 'legacy_entry'].includes(r.code)) });
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={dialogContent}>
        <DialogHeader className={dialogHeader}>
          <DialogTitle>{saved ? 'Plan rescheduled' : 'Reschedule plan'}</DialogTitle>
          <DialogDescription>Change when this approved post is planned. MCF does not publish or send anything.</DialogDescription>
        </DialogHeader>

        {saved ? (
          <>
            <div className={dialogBody} role="status">
              <p className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
                <CalendarCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
                <span>Now planned for <strong>{describePlanTime(saved.scheduledAt, saved.timezone ?? timeZone)}</strong>. Status: {saved.status}. The approved post (version {saved.contentVersion ?? entry.contentVersion}) is unchanged and nothing has been published.</span>
              </p>
            </div>
            <div className={dialogFooter}><Button type="button" onClick={() => close(false)}>Done</Button></div>
          </>
        ) : (
          <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col" noValidate>
            <div className={dialogBody}>
              <section aria-labelledby="reschedule-entry-title" className="space-y-1.5">
                <h3 id="reschedule-entry-title" className={sectionTitle}>Planned content</h3>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 text-sm">
                  <dt className="text-muted-foreground">Project</dt><dd className="truncate font-medium" title={entry.projectTitle}>{entry.projectTitle}</dd>
                  {entry.productName && (<><dt className="text-muted-foreground">Product</dt><dd className="truncate">{entry.productName}</dd></>)}
                  <dt className="text-muted-foreground">Content</dt><dd className="truncate">{entry.platform} {entry.contentType ?? ''}</dd>
                  <dt className="text-muted-foreground">Version</dt><dd>Approved version {entry.contentVersion ?? '—'}</dd>
                  <dt className="text-muted-foreground">Currently</dt><dd>{describePlanTime(base.scheduledAt, base.timezone)}</dd>
                </dl>
              </section>

              <fieldset className="space-y-3" disabled={submitting || cancelledNow}>
                <legend className={sectionTitle}>New time</legend>
                <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="reschedule-date">Date</Label>
                    <Input id="reschedule-date" type="date" required value={date} className={inputField}
                           onChange={(e) => setDate(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="reschedule-time">Time</Label>
                    <Input id="reschedule-time" type="time" required value={time} className={inputField}
                           onChange={(e) => setTime(e.target.value)} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="reschedule-zone">Time zone (IANA)</Label>
                  <Input id="reschedule-zone" list="reschedule-zone-options" required value={timeZone} className={inputField}
                         spellCheck={false} autoComplete="off" onChange={(e) => setTimeZone(e.target.value.trim())}
                         aria-invalid={!isSupportedTimeZone(timeZone)} />
                  <datalist id="reschedule-zone-options">{zones.map((z) => <option key={z} value={z} />)}</datalist>
                </div>
                <p className="text-xs text-muted-foreground">Platform: <span className="font-medium text-foreground">{entry.platform}</span> (the only supported platform in this version).</p>
              </fieldset>

              <fieldset className="space-y-1.5" disabled={submitting || cancelledNow}>
                <legend className={sectionTitle}>Planning notes</legend>
                <Label htmlFor="reschedule-notes" className="sr-only">Planning notes (optional)</Label>
                <Textarea id="reschedule-notes" value={notes} maxLength={NOTES_MAX} rows={2} className="max-h-40 min-h-16 resize-y"
                          onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
              </fieldset>

              <section aria-labelledby="reschedule-preview-title" className="space-y-1.5">
                <h3 id="reschedule-preview-title" className={sectionTitle}>Schedule preview</h3>
                <div aria-live="polite" className={`rounded-lg border p-3 text-sm ${previewError ? 'border-amber-500/40 bg-amber-500/5' : 'border-border/60 bg-muted/30'}`}>
                  {preview && (
                    <p>{timeChanged ? 'Will be planned for ' : 'Stays planned for '}<strong>{preview.text}</strong>.
                      {preview.ambiguous && ' This time occurs twice that day because the clocks go back; the first occurrence is used.'}</p>
                  )}
                  {previewError && <p className="text-amber-700 dark:text-amber-400">{previewError}</p>}
                  {preview && !timeChanged && !notesChanged && <p className="mt-1 text-muted-foreground">Change the time, time zone or notes to save.</p>}
                </div>
              </section>

              <div ref={messageRef} className="space-y-3 empty:hidden">
                {notice && (
                  <div role="status" className="flex items-start gap-2 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-sm">
                    <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-500" aria-hidden="true" /><p>{notice}</p>
                  </div>
                )}
                {failure && (
                  <div role="alert" className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                    <p className="flex items-start gap-2 font-medium text-destructive"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{failure.message}</p>
                    {failure.reasons.length > 0 && <ul className="list-disc pl-6 text-foreground/90">{failure.reasons.map((r) => <li key={r.code}>{r.message}</li>)}</ul>}
                  </div>
                )}
              </div>
            </div>

            <div className={dialogFooter}>
              <Button type="button" variant="ghost" onClick={() => close(false)} disabled={submitting}>Close</Button>
              <Button type="submit" disabled={!canSave} aria-disabled={!canSave}>
                {submitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />Saving…</> : 'Save new time'}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
