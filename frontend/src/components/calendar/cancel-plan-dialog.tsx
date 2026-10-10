'use client';

import { useRef, useState, useSyncExternalStore } from 'react';
import { AlertTriangle, CalendarX, Info, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { dialogBody, dialogContent, dialogFooter, dialogHeader } from '@/components/calendar/dialog-layout';
import { describePlanTime, planningFailureMessage } from '@/components/calendar/reschedule-plan-dialog';
import { localTimeZone } from '@/lib/calendar-range';
import { PlanningApiError, ScheduleService } from '@/lib/services/schedule.service';
import type { CalendarEntry, PlannedEntry } from '@/types/schedule';

interface CancelPlanDialogProps {
  entry: CalendarEntry;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The server confirmed the cancellation. */
  onCancelled: (entry: PlannedEntry) => void;
  /** The stored entry differs from what was shown: refresh the calendar. */
  onStale: () => void;
}

/** Confirm, then cancel a planned entry. The entry is kept (status "cancelled"); the post is not touched. */
export function CancelPlanDialog({ entry, open, onOpenChange, onCancelled, onStale }: CancelPlanDialogProps) {
  const browserZone = useSyncExternalStore(() => () => {}, localTimeZone, () => 'UTC');
  const [base, setBase] = useState({ lockVersion: entry.lockVersion, scheduledAt: entry.scheduledAt,
                                     timezone: entry.timezone || browserZone, cancelled: entry.status === 'cancelled' || entry.cancelledAt !== null });
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState<PlannedEntry | null>(null);
  const when = describePlanTime(base.scheduledAt, base.timezone);

  const close = (next: boolean) => {
    if (submitting) return;
    onOpenChange(next);
  };

  const confirm = async () => {
    if (inFlight.current || base.cancelled) return;  // one request at a time
    inFlight.current = true;
    setSubmitting(true);
    setFailure(null);
    setNotice(null);
    try {
      const cancelled = await ScheduleService.cancelPlan(entry.id, base.lockVersion);
      setDone(cancelled);
      onCancelled(cancelled);
    } catch (e) {
      const error = e instanceof PlanningApiError ? e : new PlanningApiError('server', 'The request failed.');
      if (error.hasCode('lock_conflict') || error.hasCode('cancelled')) {
        onStale();
        try {
          const latest = await ScheduleService.getPlan(entry.id);
          const gone = latest.status === 'cancelled' || latest.cancelledAt !== null;
          setBase({ lockVersion: latest.lockVersion, scheduledAt: latest.scheduledAt, timezone: latest.timezone || browserZone, cancelled: gone });
          setNotice(gone
            ? 'This plan was already cancelled somewhere else. Nothing more to do.'
            : `This plan was changed somewhere else after you opened it — it is now planned for ${describePlanTime(latest.scheduledAt, latest.timezone || browserZone)}. Nothing was cancelled. Confirm again if you still want to cancel it.`);
        } catch (inner) {
          setFailure(planningFailureMessage(inner instanceof PlanningApiError ? inner : new PlanningApiError('server', 'Could not load the latest plan.'), 'cancel'));
        }
      } else {
        setFailure(planningFailureMessage(error, 'cancel'));
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={`${dialogContent} max-w-[480px]`}>
        <DialogHeader className={dialogHeader}>
          <DialogTitle>{done ? 'Plan cancelled' : 'Cancel this plan?'}</DialogTitle>
          <DialogDescription>Cancelling removes the plan from the calendar only. It does not publish anything and does not delete or change the post.</DialogDescription>
        </DialogHeader>
        <div className={dialogBody}>
          {done ? (
            <p role="status" className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
              <CalendarX className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
              <span>The plan for <strong>{when}</strong> is cancelled. It stays in the calendar history (use “Show cancelled” to see it). The approved post is unchanged.</span>
            </p>
          ) : (
            <p className="text-sm">
              Cancel the plan for <strong>{entry.projectTitle}</strong> on <strong>{when}</strong>
              {entry.contentVersion != null && <> (approved version {entry.contentVersion})</>}?
            </p>
          )}
          {notice && (
            <div role="status" className="flex items-start gap-2 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-sm">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-500" aria-hidden="true" /><p>{notice}</p>
            </div>
          )}
          {failure && (
            <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm font-medium text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{failure}
            </p>
          )}
        </div>
        <div className={dialogFooter}>
          {done || base.cancelled ? (
            <Button type="button" onClick={() => close(false)}>Done</Button>
          ) : (
            <>
              <Button type="button" variant="ghost" onClick={() => close(false)} disabled={submitting}>Keep plan</Button>
              <Button type="button" onClick={confirm} disabled={submitting} aria-disabled={submitting}
                      className="bg-destructive text-white hover:bg-destructive/90">
                {submitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />Cancelling…</> : 'Cancel plan'}
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
