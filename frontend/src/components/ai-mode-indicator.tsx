"use client"

import React, { useEffect, useState } from 'react';
import { AlertTriangle, Bot, Sparkles } from 'lucide-react';
import { AiMode, AiModeService } from '@/lib/services/ai-mode.service';
import { cn } from '@/lib/utils';

const PROVIDER_LABEL: Record<string, string> = { claude: 'Claude', openai: 'OpenAI' };

/** States which AI mode generation actions will use. Configuration only: it never claims a verified connection. */
export function AiModeIndicator() {
  const [mode, setMode] = useState<AiMode | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    AiModeService.get()
      .then((m) => { if (!cancelled) setMode(m); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, []);

  const base = 'inline-flex items-start gap-1.5 text-xs leading-snug px-2.5 py-1 rounded-lg border max-w-full';
  if (failed) {
    return <p className={cn(base, 'bg-muted text-muted-foreground border-border/50')}>AI mode unknown: could not read the backend configuration.</p>;
  }
  if (!mode) return null;

  if (mode.mode === 'demo') {
    return (
      <p className={cn(base, 'bg-muted/60 text-muted-foreground border-border/50')} data-testid="ai-mode-demo">
        <Bot className="w-3.5 h-3.5 shrink-0 mt-px" />
        <span><strong className="text-foreground">Demo Mode</strong> — output is deterministic; no third-party AI API is called.</span>
      </p>
    );
  }

  const provider = PROVIDER_LABEL[mode.provider] ?? mode.provider;
  if (!mode.configured) {
    return (
      <p className={cn(base, 'bg-destructive/10 text-destructive border-destructive/20')} data-testid="ai-mode-misconfigured">
        <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
        <span><strong>Real AI selected ({provider}) but not configured:</strong> {mode.configurationProblem} Generation actions will fail.</span>
      </p>
    );
  }
  return (
    <p className={cn(base, 'bg-amber-500/10 text-amber-500 border-amber-500/20')} data-testid="ai-mode-real">
      <Sparkles className="w-3.5 h-3.5 shrink-0 mt-px" />
      <span>
        <strong>Real AI — {provider}{mode.model ? ` · ${mode.model}` : ''}.</strong> Generation actions call a paid API and can incur
        charges. Configured, connection not verified.{mode.singleAttempt && ' Single-attempt mode: at most one request per AI step, no retries.'}
      </span>
    </p>
  );
}
