'use client';

import { useState, useEffect } from 'react';
import { DiagnosticsService, DiagnosticsResponse } from '@/lib/services/diagnostics.service';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Loader2, RefreshCw, CheckCircle2, AlertTriangle, XCircle, Info, MinusCircle, HelpCircle } from 'lucide-react';

// Health states: Healthy/Ready/Enabled (ok), Warning/Degraded (attention), Unavailable (failed), Unknown (could not be
// determined), Not checked (did not run because something it depends on failed), Not configured.
const getStatusIcon = (status: string) => {
  switch (status) {
    case 'Healthy':
    case 'Ready':
    case 'Enabled':
      return <CheckCircle2 className="w-5 h-5 text-emerald-500" aria-hidden="true" />;
    case 'Warning':
    case 'Degraded':
    case 'Demo':
      return <AlertTriangle className="w-5 h-5 text-amber-500" aria-hidden="true" />;
    case 'Unavailable':
      return <XCircle className="w-5 h-5 text-red-500" aria-hidden="true" />;
    case 'Not checked':
      return <MinusCircle className="w-5 h-5 text-slate-400 dark:text-muted-foreground" aria-hidden="true" />;
    case 'Unknown':
      return <HelpCircle className="w-5 h-5 text-slate-400 dark:text-muted-foreground" aria-hidden="true" />;
    case 'Not configured':
    default:
      return <Info className="w-5 h-5 text-slate-400 dark:text-muted-foreground" aria-hidden="true" />;
  }
};

const getBadgeStyle = (status: string) => {
  switch (status) {
    case 'Healthy':
    case 'Ready':
    case 'Enabled':
      return 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-500 border border-emerald-200 dark:border-emerald-500/20';
    case 'Warning':
    case 'Degraded':
    case 'Demo':
      return 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-500 border border-amber-200 dark:border-amber-500/20';
    case 'Unavailable':
      return 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-500 border border-red-200 dark:border-red-500/20';
    case 'Not checked':
      return 'bg-transparent text-slate-500 dark:text-muted-foreground border border-dashed border-slate-300 dark:border-border';
    case 'Unknown':
    case 'Not configured':
    default:
      return 'bg-slate-50 dark:bg-muted text-slate-600 dark:text-muted-foreground border border-slate-200 dark:border-border';
  }
};

const cardClass = 'bg-white dark:bg-card border border-slate-200 dark:border-border shadow-sm overflow-hidden';
const cardHeader = 'pb-4 pt-6 px-6 border-b border-slate-100 dark:border-border bg-slate-50/50 dark:bg-muted/30';

function Row({ title, status, message, badge, details }: { title: string; status: string; message?: string | null; badge?: string; details?: (string | null | false | undefined)[] }) {
  const lines = (details ?? []).filter(Boolean) as string[];
  return (
    <div className="flex items-start justify-between gap-3 p-3.5 rounded-xl border border-slate-100 dark:border-border bg-white dark:bg-card shadow-sm">
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 shrink-0">{getStatusIcon(status)}</span>
        <div className="min-w-0">
          <div className="font-semibold text-foreground">{title}</div>
          {message && <div className="text-xs text-slate-500 dark:text-muted-foreground">{message}</div>}
          {lines.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs text-slate-500 dark:text-muted-foreground">
              {lines.map((line) => <li key={line} className="break-words">{line}</li>)}
            </ul>
          )}
        </div>
      </div>
      <div className={`shrink-0 font-bold text-xs ${getBadgeStyle(status)} px-2.5 py-1 rounded-md`}>
        <span className="sr-only">Status: </span>{badge ?? status}
      </div>
    </div>
  );
}

export default function DiagnosticsPage() {
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDiagnostics = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await DiagnosticsService.getDiagnostics();
      setData(response);
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : 'Failed to load diagnostics. Backend may be offline.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDiagnostics();
  }, []);

  const ai = data?.ai;
  const emb = data?.embeddings;
  const ing = data?.ingestion;
  const migration = data?.migration;
  const sourcesBreakdown = ing ? Object.entries(ing.sourcesByStatus).sort().map(([s, n]) => `${n} ${s}`).join(' · ') : '';

  return (
    <div className="w-full max-w-5xl mx-auto px-6 md:px-8 py-4 space-y-10 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-foreground mb-2">System Diagnostics</h1>
          <p className="text-muted-foreground">
            Read-only health and configuration status of the MCF architecture. Running these checks never calls an AI provider or changes any data.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={loadDiagnostics} disabled={loading} className="gap-2 bg-white dark:bg-card border border-slate-200 dark:border-border text-slate-700 dark:text-foreground hover:bg-slate-50 dark:hover:bg-muted shadow-sm rounded-full">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Refresh Diagnostics
          </Button>
          <Button
            onClick={() => {
              if (confirm('Clear local cache and reset state?')) {
                localStorage.clear();
                sessionStorage.clear();
                window.location.reload();
              }
            }}
            variant="outline"
            className="gap-2 shadow-sm rounded-full text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
          >
            <RefreshCw className="w-4 h-4" />
            Clear Local Cache & Reset
          </Button>
        </div>
      </div>

      {error && (
        <div role="alert" className="bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-500 border border-red-200 dark:border-red-500/20 shadow-sm rounded-md p-4 flex items-start gap-3">
          <XCircle className="w-5 h-5 mt-0.5" />
          <div>
            <h3 className="font-semibold">Connection Error</h3>
            <p className="text-sm opacity-90">{error}</p>
          </div>
        </div>
      )}

      {loading && !data && (
        <div role="status" className="flex justify-center items-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <span className="sr-only">Running checks…</span>
        </div>
      )}

      {data?.overall && (
        <div className={`flex flex-wrap items-center justify-between gap-3 rounded-xl p-4 ${getBadgeStyle(data.overall.status)}`} aria-live="polite">
          <div className="flex items-center gap-3">
            {getStatusIcon(data.overall.status)}
            <div>
              <div className="font-semibold">Overall: {data.overall.status}</div>
              <div className="text-sm font-normal opacity-90">{data.overall.message}</div>
            </div>
          </div>
          {data.checkedAt && <div className="text-xs font-normal opacity-80">Checked {new Date(data.checkedAt).toLocaleString()}</div>}
        </div>
      )}

      {data && (
        <div className="grid gap-6 md:grid-cols-2">

          <Card className={cardClass}>
            <CardHeader className={cardHeader}>
              <CardTitle className="text-xl font-bold flex items-center gap-2">Core Infrastructure</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-6">
              <Row title="Frontend" status="Healthy" message="React / Next.js" badge="Connected" />
              <Row title="Backend API" status={data.backend.status} message={data.backend.message} />
              <Row title="PostgreSQL" status={data.database.status} message={data.database.message} />
              <Row title="Vector Store" status={data.vectorStore.status} message={data.vectorStore.message} />
              {migration && (
                <Row title="Database Schema" status={migration.status} message={migration.message}
                     details={[migration.currentRevision && `Database revision: ${migration.currentRevision}`,
                               migration.headRevision && `Code expects: ${migration.headRevision}`]} />
              )}
            </CardContent>
          </Card>

          <Card className={cardClass}>
            <CardHeader className={cardHeader}>
              <CardTitle className="text-xl font-bold flex items-center gap-2">AI & Data Services</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-6">
              {ai && (
                <Row title={`AI Provider (${ai.provider})`} status={ai.status} message={ai.message}
                     details={[
                       `Mode: ${ai.mode === 'real' ? 'Real AI (may incur charges)' : 'Demo (no external calls, no charges)'}`,
                       `Model: ${ai.model}`,
                       ai.mode === 'real' && `Credentials: ${ai.credentialsConfigured ? 'configured on the server' : 'not set'}`,
                       ai.mode === 'real' && 'Connection: not verified (diagnostics make no provider calls)',
                       ai.singleAttempt && 'Single attempt per AI step (no retries)',
                     ]} />
              )}
              {emb && (
                <Row title={`Embedding (${emb.provider})`} status={emb.status} message={emb.message}
                     details={[emb.model && `Model: ${emb.model}`,
                               `Retrieval relevance: ${emb.semantic ? 'keyword + semantic' : 'keyword only'}`,
                               emb.provider !== 'demo' && `Credentials: ${emb.credentialsConfigured ? 'configured on the server (not verified)' : 'not set'}`]} />
              )}
              <Row title="RAG Retrieval" status={data.rag.status} message={data.rag.message} />
              <Row title="Environment" status={data.environment.mode === 'Demo' ? 'Demo' : 'Healthy'} message={data.environment.message}
                   badge={`${data.environment.mode} Mode`} />
            </CardContent>
          </Card>

          {ing && (
            <Card className={`${cardClass} md:col-span-2`}>
              <CardHeader className={cardHeader}>
                <CardTitle className="text-xl font-bold flex items-center gap-2">Your Sources & Indexing</CardTitle>
                <CardDescription>Only the sources in your own projects are counted.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 p-6">
                <Row title="Source indexing" status={ing.status} message={ing.message} />
                {ing.status !== 'Not checked' && (
                  <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    {[['Sources', ing.sourcesTotal], ['Indexed chunks', ing.chunksTotal], ['Out-of-date chunks', ing.staleChunks],
                      ['Chunks without current embedding details', ing.otherEmbeddingChunks]].map(([label, value]) => (
                      <div key={label as string} className="rounded-lg border border-slate-100 dark:border-border p-3">
                        <dt className="text-xs text-muted-foreground">{label}</dt>
                        <dd className="text-lg font-semibold tabular-nums">{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {sourcesBreakdown && <p className="text-xs text-muted-foreground">By status: {sourcesBreakdown}</p>}
                {ing.failedSources.length > 0 && (
                  <div className="text-sm">
                    <p className="font-medium text-foreground">Recently failed sources</p>
                    <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                      {ing.failedSources.map((f, i) => (
                        <li key={`${f.name}-${i}`} className="break-words">{f.name}{f.updatedAt ? ` — ${new Date(f.updatedAt).toLocaleString()}` : ''}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

        </div>
      )}
    </div>
  );
}
