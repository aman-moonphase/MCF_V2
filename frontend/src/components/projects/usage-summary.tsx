"use client"

import React from 'react';
import { GeneratedDraft } from '@/lib/services/generation.service';

const fmt = (n: number) => n.toLocaleString();

/** API usage of the request(s) that generated a saved post. Demo Mode makes no API calls, so it shows none. */
export function UsageSummary({ draft }: { draft: GeneratedDraft }) {
  const usage = draft.usage;
  if (!usage) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="usage-none">
        {draft.isDemo ? 'No API usage — generated in Demo Mode.' : 'API usage was not recorded for this post.'}
      </p>
    );
  }
  const t = usage.totals;
  const cache = (t.cacheReadInputTokens || 0) + (t.cacheCreationInputTokens || 0) > 0
    ? ` · cache read ${fmt(t.cacheReadInputTokens)} / write ${fmt(t.cacheCreationInputTokens)}` : '';
  return (
    <p className="text-xs text-muted-foreground" title={usage.costNote} data-testid="usage-summary">
      API usage (generated as version {usage.generatedVersion}, {usage.models.join(', ')}): {usage.requestCount} request
      {usage.requestCount === 1 ? '' : 's'}{usage.failedRequests ? ` (${usage.failedRequests} failed)` : ''} · {fmt(t.inputTokens)} input /{' '}
      {fmt(t.outputTokens)} output tokens{cache} · {(usage.durationMs / 1000).toFixed(1)}s ·{' '}
      {usage.estimatedCostUsd != null ? <>estimated cost ${usage.estimatedCostUsd.toFixed(4)} (estimate)</> : 'no cost estimate for this model'}
    </p>
  );
}
