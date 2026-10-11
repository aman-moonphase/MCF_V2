'use client';

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { DiagnosticsService, DiagnosticsResponse } from '@/lib/services/diagnostics.service';
import {
  SettingsApiError, SettingsService, type CalendarDefaultView, type UserSettings, type UserSettingsInput,
} from '@/lib/services/settings.service';
import { setCachedUserSettings } from '@/lib/use-user-settings';
import { isSupportedTimeZone, knownTimeZones } from '@/lib/calendar-time';
import { localTimeZone } from '@/lib/calendar-range';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2, ShieldCheck, Database, BrainCircuit, Server, Settings2, SlidersHorizontal, CheckCircle2, AlertTriangle, Activity } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

const VIEW_OPTIONS: { value: CalendarDefaultView; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'week', label: 'Week' },
  { value: 'day', label: 'Day' },
];
const TIME_PATTERN = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const fieldLabel = 'text-xs uppercase tracking-wider text-slate-500 dark:text-muted-foreground font-semibold';
const readOnlyField = 'bg-slate-50 dark:bg-muted/50 border-slate-200 dark:border-border shadow-sm h-11';
const cardClass = 'bg-white dark:bg-card border border-slate-200 dark:border-border shadow-sm overflow-hidden';
const cardHeader = 'border-b border-slate-100 dark:border-border pb-5 pt-6 px-6 bg-slate-50/50 dark:bg-muted/30';

type Form = { timezone: string; calendarDefaultView: CalendarDefaultView; defaultPlanTime: string };
const toForm = (s: UserSettings): Form => ({ timezone: s.timezone ?? '', calendarDefaultView: s.calendarDefaultView, defaultPlanTime: s.defaultPlanTime });
const noSubscription = () => () => {};

function settingsErrorText(error: SettingsApiError): string {
  if (error.kind === 'auth') return 'Your session has expired. Sign in again to manage your preferences.';
  if (error.kind === 'network') return 'Could not reach the server. Check your connection and try again.';
  if (error.kind === 'validation') return `The server rejected these values: ${error.message}`;
  return `The server could not complete the request: ${error.message}`;
}

/** Preferences for the signed-in user, saved on the server. Nothing here is a credential or provider setting. */
function PreferencesCard() {
  const browserZone = useSyncExternalStore(noSubscription, localTimeZone, () => '');
  const zones = useMemo(() => knownTimeZones(), []);
  const [stored, setStored] = useState<UserSettings | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [loadError, setLoadError] = useState<SettingsApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let current = true;
    SettingsService.get()
      .then((s) => {
        if (!current) return;
        setStored(s);
        setForm(toForm(s));
        setLoadError(null);
      })
      .catch((e: unknown) => {
        if (current) setLoadError(e instanceof SettingsApiError ? e : new SettingsApiError('server', 'Could not load your preferences.'));
      });
    return () => { current = false; };
  }, [reloadKey]);

  const problems: Partial<Record<keyof Form, string>> = {};
  if (form) {
    if (form.timezone.trim() && !isSupportedTimeZone(form.timezone.trim())) problems.timezone = 'Enter a valid IANA time zone, e.g. Asia/Kolkata — or leave it empty to use your browser’s zone.';
    if (!TIME_PATTERN.test(form.defaultPlanTime)) problems.defaultPlanTime = 'Enter a time as HH:MM (24-hour).';
  }
  const dirty = !!(form && stored) && JSON.stringify({ ...form, timezone: form.timezone.trim() }) !== JSON.stringify(toForm(stored));
  const valid = Object.keys(problems).length === 0;

  const update = (patch: Partial<Form>) => {
    setForm((f) => (f ? { ...f, ...patch } : f));
    setSavedAt(null);
    setSaveError(null);
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form || !dirty || !valid || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const input: UserSettingsInput = { timezone: form.timezone.trim() || null, calendarDefaultView: form.calendarDefaultView, defaultPlanTime: form.defaultPlanTime };
      const result = await SettingsService.save(input);  // success only once the server confirms
      setStored(result);
      setForm(toForm(result));
      setCachedUserSettings(result);
      setSavedAt(result.updatedAt);
    } catch (e) {
      setSaveError(settingsErrorText(e instanceof SettingsApiError ? e : new SettingsApiError('server', 'The request failed.')));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={cardClass}>
      <CardHeader className={cardHeader}>
        <CardTitle className="flex items-center gap-2 text-xl font-bold">
          <SlidersHorizontal className="w-6 h-6 text-primary" />
          Your Preferences
        </CardTitle>
        <CardDescription className="pt-1">Saved to your account and used on any device you sign in from.</CardDescription>
      </CardHeader>
      <CardContent className="p-6">
        {!form && !loadError && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" />Loading your preferences…</p>
        )}
        {loadError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <p className="text-destructive">{settingsErrorText(loadError)}</p>
            {loadError.kind === 'auth'
              ? <Button asChild size="sm"><Link href="/login">Sign in</Link></Button>
              : <Button size="sm" variant="outline" onClick={() => setReloadKey((k) => k + 1)}>Retry</Button>}
          </div>
        )}
        {form && stored && (
          <form onSubmit={save} noValidate className="space-y-6">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="pref-view" className={fieldLabel}>Calendar opens in</Label>
                <Select value={form.calendarDefaultView} onValueChange={(v) => update({ calendarDefaultView: v as CalendarDefaultView })} disabled={saving}>
                  <SelectTrigger id="pref-view" className="h-11"><SelectValue /></SelectTrigger>
                  <SelectContent>{VIEW_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label} view</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="pref-time" className={fieldLabel}>Default planning time</Label>
                <Input id="pref-time" type="time" value={form.defaultPlanTime} className="h-11" disabled={saving}
                       onChange={(e) => update({ defaultPlanTime: e.target.value })} aria-invalid={!!problems.defaultPlanTime}
                       aria-describedby="pref-time-help" />
                <p id="pref-time-help" className={`text-xs ${problems.defaultPlanTime ? 'text-destructive' : 'text-muted-foreground'}`}>
                  {problems.defaultPlanTime ?? 'Pre-filled when you add an approved post to the calendar.'}
                </p>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="pref-zone" className={fieldLabel}>Default planning time zone (IANA)</Label>
                <Input id="pref-zone" list="pref-zone-options" value={form.timezone} className="h-11" disabled={saving}
                       placeholder={browserZone ? `Your browser’s zone (${browserZone})` : 'Your browser’s zone'}
                       spellCheck={false} autoComplete="off" onChange={(e) => update({ timezone: e.target.value })}
                       aria-invalid={!!problems.timezone} aria-describedby="pref-zone-help" />
                <datalist id="pref-zone-options">{zones.map((z) => <option key={z} value={z} />)}</datalist>
                <p id="pref-zone-help" className={`text-xs ${problems.timezone ? 'text-destructive' : 'text-muted-foreground'}`}>
                  {problems.timezone ?? 'Used for new plans. Leave empty to use the time zone of the browser you are using. The calendar itself always shows times in your browser’s zone.'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 dark:border-border pt-4">
              <p className="text-sm" aria-live="polite">
                {saving ? <span className="text-muted-foreground">Saving…</span>
                  : saveError ? <span role="alert" className="flex items-center gap-1.5 text-destructive"><AlertTriangle className="w-4 h-4" />{saveError} Nothing was saved.</span>
                  : dirty ? <span className="text-amber-600 dark:text-amber-400">You have unsaved changes.</span>
                  : savedAt ? <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400"><CheckCircle2 className="w-4 h-4" />Saved.</span>
                  : <span className="text-muted-foreground">{stored.saved ? 'Your saved preferences are in use.' : 'Using the default preferences (nothing saved yet).'}</span>}
              </p>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" disabled={!dirty || saving} onClick={() => { setForm(toForm(stored)); setSaveError(null); }}>Discard changes</Button>
                <Button type="submit" disabled={!dirty || !valid || saving} aria-disabled={!dirty || !valid || saving}>
                  {saving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Saving…</> : 'Save preferences'}
                </Button>
              </div>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const response = await DiagnosticsService.getDiagnostics();
        setData(response);
      } catch (err: unknown) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadSettings();
  }, []);

  const isDemoMode = data?.environment.mode === 'Demo';

  return (
    <div className="w-full max-w-5xl mx-auto px-6 md:px-8 py-4 space-y-10 animate-in fade-in duration-500">
      <div className="mb-8">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-foreground mb-2">Application Settings</h1>
        <p className="text-muted-foreground">
          Your preferences, and the application configuration. Configuration is read-only here: it is managed in the server environment, and credentials are never shown.
        </p>
      </div>

      {isDemoMode && (
        <Alert className="bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-500 border-amber-200 dark:border-amber-500/20 shadow-sm">
          <AlertTitle className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="w-4 h-4" />
            Demo Mode Active
          </AlertTitle>
          <AlertDescription>
            You are running MCF in Demo Mode. AI features will use deterministic fallback providers and will not require real API keys.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6">
        <PreferencesCard />

        {loading && (
          <div className="flex justify-center items-center py-10"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>
        )}
        {!loading && !data && (
          <Alert variant="destructive" className="bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-500 border border-red-200 dark:border-red-500/20 shadow-sm">
            <AlertTitle>Cannot load the application configuration</AlertTitle>
            <AlertDescription>The backend API did not respond. Make sure the server is running, then reload this page.</AlertDescription>
          </Alert>
        )}

        {data && (
          <>
            {/* Application & Environment */}
            <Card className={cardClass}>
              <CardHeader className={cardHeader}>
                <CardTitle className="flex items-center gap-2 text-xl font-bold">
                  <Server className="w-6 h-6 text-primary" />
                  Application & Environment
                </CardTitle>
                <CardDescription className="pt-1">Core system environment configuration (read-only).</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6 p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Environment Mode</Label>
                    <Input value={data.environment.mode} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2">
                    <Label className={fieldLabel}>API Status</Label>
                    <Input value={data.backend.status} readOnly className={readOnlyField} />
                  </div>
                </div>
                <p className="text-sm text-muted-foreground">
                  Health checks (database, migrations, AI and indexing) are on the{' '}
                  <Link href="/diagnostics" className="inline-flex items-center gap-1 font-medium text-primary hover:underline"><Activity className="w-3.5 h-3.5" />Diagnostics</Link> page.
                </p>
              </CardContent>
            </Card>

            {/* AI Configuration */}
            <Card className={cardClass}>
              <CardHeader className={cardHeader}>
                <CardTitle className="flex items-center gap-2 text-xl font-bold">
                  <BrainCircuit className="w-6 h-6 text-primary" />
                  AI Configuration
                </CardTitle>
                <CardDescription className="pt-1">Language model provider (read-only; set in the server environment).</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6 p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label className={fieldLabel}>AI Provider</Label>
                    <Input value={data.ai.provider} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Model</Label>
                    <Input value={data.ai.model} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label className={fieldLabel}>Provider Credentials</Label>
                    <div className="flex items-center p-3 rounded-lg border border-slate-200 dark:border-border bg-slate-50 dark:bg-muted/50 shadow-sm min-h-11">
                      {data.ai.mode === 'demo' || data.ai.provider === 'demo' ? (
                        <span className="text-sm font-semibold text-slate-500 dark:text-muted-foreground flex items-center gap-2">
                          <ShieldCheck className="w-5 h-5" /> Not required in Demo Mode
                        </span>
                      ) : data.ai.credentialsConfigured ? (
                        <span className="text-sm font-semibold text-emerald-600 dark:text-emerald-500 flex items-center gap-2">
                          <ShieldCheck className="w-5 h-5" /> Configured on the server — connection not verified
                        </span>
                      ) : (
                        <span className="text-sm font-semibold text-red-600 dark:text-red-500 flex items-center gap-2">
                          <Settings2 className="w-5 h-5" /> Not set on the server
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Source & RAG */}
            <Card className={cardClass}>
              <CardHeader className={cardHeader}>
                <CardTitle className="flex items-center gap-2 text-xl font-bold">
                  <Database className="w-6 h-6 text-primary" />
                  Source & RAG Configuration
                </CardTitle>
                <CardDescription className="pt-1">Vector store and retrieval settings (read-only).</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6 p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Embedding Provider</Label>
                    <Input value={data.embeddings.model ? `${data.embeddings.provider} (${data.embeddings.model})` : data.embeddings.provider} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Vector Store Extension</Label>
                    <Input value={data.vectorStore.extension || 'None'} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Retrieval Service Status</Label>
                    <Input value={data.rag.status} readOnly className={readOnlyField} />
                  </div>
                  <div className="space-y-2">
                    <Label className={fieldLabel}>Retrieval Relevance</Label>
                    <Input value={data.embeddings.semantic ? 'Keyword + semantic' : 'Keyword only (demo embeddings carry no meaning)'} readOnly className={readOnlyField} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
