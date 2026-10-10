'use client';

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { AlertTriangle, CalendarCheck, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { InstantError, formatInstant, isSupportedTimeZone, knownTimeZones, zonedDateTimeToIso } from '@/lib/calendar-time';
import { localTimeZone } from '@/lib/calendar-range';
import { NOTES_MAX, dialogBody, dialogContent, dialogFooter, dialogHeader, inputField, sectionTitle } from '@/components/calendar/dialog-layout';
import { PlanningApiError, ScheduleService } from '@/lib/services/schedule.service';
import type { PlannedEntry, PlanningRefusal } from '@/types/schedule';

export interface PlanPostSummary {
  projectId: string;
  projectTitle: string;
  productId: string | null;
  productName: string | null;
  contentType: string;
  /** Display name, e.g. "LinkedIn" — sent as the platform. */
  platform: string;
  version: number;
}

interface PlanPostDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  post: PlanPostSummary;
  /** Called after the server confirmed the plan. */
  onPlanned: (entry: PlannedEntry) => void;
}

const noSubscription = () => () => {};
// "Now" for the past-time hint, refreshed every 30 s (the server re-checks the time on submit).
const CLOCK_MS = 30000;
const subscribeClock = (onChange: () => void) => {
  const id = setInterval(onChange, CLOCK_MS);
  return () => clearInterval(id);
};
const readClock = () => Math.floor(Date.now() / CLOCK_MS) * CLOCK_MS;
const field = inputField;
const body = dialogBody;
const footer = dialogFooter;

function todayIn(timeZone: string): string {
  return formatInstant(new Date(), timeZone, { year: 'numeric', month: '2-digit', day: '2-digit' }, 'en-CA');
}

function errorMessage(error: PlanningApiError): string {
  switch (error.kind) {
    case 'auth': return 'Your session has expired. Sign in again, then plan the post. Nothing was saved.';
    case 'not_found': return 'This project was not found. Nothing was saved.';
    case 'refused': return 'This post cannot be planned right now. Nothing was saved.';
    case 'validation': return 'The planned time is not valid. Nothing was saved.';
    case 'network': return error.message;
    default: return `The plan could not be saved: ${error.message}`;
  }
}

/** Plan an approved post on the calendar. Planning only: nothing is published or sent anywhere. */
export function PlanPostDialog({ open, onOpenChange, post, onPlanned }: PlanPostDialogProps) {
  const [date, setDate] = useState('');
  const [time, setTime] = useState('09:00');
  // Detected in the browser only (never the server's zone); the user can change it.
  const detectedZone = useSyncExternalStore(noSubscription, localTimeZone, () => '');
  const [zoneInput, setZoneInput] = useState<string | null>(null);
  const now = useSyncExternalStore(subscribeClock, readClock, () => 0);
  const timeZone = zoneInput ?? detectedZone;
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const [failure, setFailure] = useState<{ message: string; reasons: PlanningRefusal[] } | null>(null);
  const [saved, setSaved] = useState<PlannedEntry | null>(null);
  const zones = useMemo(() => knownTimeZones(), []);
  const failureRef = useRef<HTMLDivElement>(null);
  // The body scrolls: bring a new error into view (the footer stays visible regardless).
  useEffect(() => {
    if (failure) failureRef.current?.scrollIntoView({ block: 'nearest' });
  }, [failure]);

  const reset = () => {
    setDate('');
    setTime('09:00');
    setZoneInput(null);
    setNotes('');
    setFailure(null);
    setSaved(null);
  };
  const close = (next: boolean) => {
    if (submitting) return;  // never close mid-request
    onOpenChange(next);
    if (!next) reset();
  };

  // Live preview of the exact instant, or why it cannot be used.
  let preview: { text: string; iso: string; ambiguous: boolean } | null = null;
  let previewError: string | null = null;
  if (date && time && timeZone) {
    try {
      const zoned = zonedDateTimeToIso(date, time, timeZone);
      if (zoned.instantMs <= now) {
        previewError = 'That time is in the past. Choose a future date and time.';
      } else {
        preview = {
          text: `${formatInstant(zoned.iso, timeZone, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })} in ${timeZone} (UTC${zoned.offset})`,
          iso: zoned.iso,
          ambiguous: zoned.ambiguous,
        };
      }
    } catch (e) {
      previewError = e instanceof InstantError ? e.message : 'That date or time is not valid.';
    }
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlight.current || !preview) return;  // one request at a time
    if (zonedDateTimeToIso(date, time, timeZone).instantMs <= Date.now()) {
      setFailure({ message: 'That time is in the past. Choose a future date and time. Nothing was saved.', reasons: [] });
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    setFailure(null);
    try {
      const entry = await ScheduleService.planPost(post.projectId, {
        scheduledAt: preview.iso, timezone: timeZone, platform: post.platform,
        notes: notes.trim() || undefined, productId: post.productId ?? undefined,
      });
      setSaved(entry);
      onPlanned(entry);
    } catch (e) {
      const error = e instanceof PlanningApiError ? e : new PlanningApiError('server', 'The plan could not be saved.');
      setFailure({ message: errorMessage(error), reasons: error.reasons });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      {/* Constrained to the viewport (safe areas included): the header and footer stay put, only the body scrolls. */}
      <DialogContent className={dialogContent}>
        <DialogHeader className={dialogHeader}>
          <DialogTitle>{saved ? 'Added to the calendar' : 'Add to Calendar'}</DialogTitle>
          <DialogDescription>
            MCF plans when this approved post should go out. It does not publish or send anything.
          </DialogDescription>
        </DialogHeader>

        {saved ? (
          <>
            <div className={body} role="status">
              <ApprovedSummary post={post} />
              <p className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
                <CalendarCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
                <span>
                  Planned for <strong>{formatInstant(saved.scheduledAt, saved.timezone ?? timeZone, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</strong>
                  {' '}({saved.timezone}). Status: {saved.status}. Nothing has been published.
                </span>
              </p>
            </div>
            <div className={footer}>
              <Button asChild variant="outline"><Link href="/calendar">Open Calendar</Link></Button>
              <Button type="button" onClick={() => close(false)}>Done</Button>
            </div>
          </>
        ) : (
          <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col" noValidate>
            <div className={body}>
              <ApprovedSummary post={post} />

              <fieldset className="space-y-3" disabled={submitting}>
                <legend className={sectionTitle}>Schedule</legend>
                <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="plan-date">Date</Label>
                    <Input id="plan-date" type="date" required value={date} className={field}
                           min={isSupportedTimeZone(timeZone) ? todayIn(timeZone) : undefined}
                           onChange={(e) => setDate(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="plan-time">Time</Label>
                    <Input id="plan-time" type="time" required value={time} className={field}
                           onChange={(e) => setTime(e.target.value)} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="plan-zone">Time zone (IANA)</Label>
                  <Input id="plan-zone" list="plan-zone-options" required value={timeZone} className={field} spellCheck={false}
                         autoComplete="off" onChange={(e) => setZoneInput(e.target.value.trim())} aria-describedby="plan-zone-help" />
                  <datalist id="plan-zone-options">{zones.map((z) => <option key={z} value={z} />)}</datalist>
                  <p id="plan-zone-help" className="text-xs text-muted-foreground">Detected from your browser. Change it if the post is planned for another region.</p>
                </div>
              </fieldset>

              <fieldset className="space-y-1.5" disabled={submitting}>
                <legend className={sectionTitle}>Planning notes</legend>
                <Label htmlFor="plan-notes" className="sr-only">Planning notes (optional)</Label>
                <Textarea id="plan-notes" value={notes} maxLength={NOTES_MAX} rows={2} className="max-h-40 min-h-16 resize-y"
                          onChange={(e) => setNotes(e.target.value)} placeholder="Optional — e.g. launch week, share after the webinar" />
              </fieldset>

              <section aria-labelledby="plan-preview-title" className="space-y-1.5">
                <h3 id="plan-preview-title" className={sectionTitle}>Schedule preview</h3>
                <div aria-live="polite" className={`rounded-lg border p-3 text-sm ${previewError ? 'border-amber-500/40 bg-amber-500/5' : 'border-border/60 bg-muted/30'}`}>
                  {preview && (
                    <p className="text-foreground">
                      Will be planned for <strong>{preview.text}</strong>.
                      {preview.ambiguous && ' This time occurs twice that day because the clocks go back; the first occurrence is used.'}
                    </p>
                  )}
                  {previewError && <p className="text-amber-700 dark:text-amber-400">{previewError}</p>}
                  {!preview && !previewError && <p className="text-muted-foreground">Choose a date, time and time zone to see the exact planned time.</p>}
                </div>
              </section>

              {failure && (
                <div ref={failureRef} role="alert" className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                  <p className="flex items-start gap-2 font-medium text-destructive"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{failure.message}</p>
                  {failure.reasons.length > 0 && (
                    <ul className="list-disc pl-6 text-foreground/90">{failure.reasons.map((r) => <li key={r.code}>{r.message}</li>)}</ul>
                  )}
                </div>
              )}
            </div>

            <div className={footer}>
              <Button type="button" variant="ghost" onClick={() => close(false)} disabled={submitting}>Cancel</Button>
              <Button type="submit" disabled={!preview || submitting} aria-disabled={!preview || submitting}>
                {submitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />Saving…</> : 'Add to Calendar'}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Compact summary of the exact approved version being planned. */
function ApprovedSummary({ post }: { post: PlanPostSummary }) {
  return (
    <section aria-labelledby="plan-post-title" className="space-y-1.5">
      <h3 id="plan-post-title" className={sectionTitle}>Approved content</h3>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 text-sm">
        <dt className="text-muted-foreground">Project</dt><dd className="truncate font-medium" title={post.projectTitle}>{post.projectTitle}</dd>
        {post.productName && (<><dt className="text-muted-foreground">Product</dt><dd className="truncate" title={post.productName}>{post.productName}</dd></>)}
        <dt className="text-muted-foreground">Content</dt><dd className="truncate">{post.platform} {post.contentType}</dd>
        <dt className="text-muted-foreground">Version</dt><dd>Approved version {post.version}</dd>
      </dl>
    </section>
  );
}
