"use client";

import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ProjectService } from "@/lib/project-service";
import {
  FileText,
  ExternalLink,
  Copy,
  Check,
  AlertCircle,
  Info,
  ShieldAlert,
  Loader2,
  Database,
} from "lucide-react";
import { toast } from "sonner";

export interface SourceInspectionDialogProps {
  projectId: string;
  projectTitle: string;
  sourceReference: string;
  sourceType: string;
  isOpen: boolean;
  onClose: () => void;
}

interface IngestedSource {
  id: string;
  projectId: string;
  name: string;
  sourceType: string;
  sourceUrl?: string | null;
  status: string;
  extractedText?: string | null;
  charCount: number;
  chunkCount: number;
  contentHash?: string | null;
  embeddingProvider?: string | null;
  embeddingModel?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  metadata?: Record<string, any> | null;
}

interface SourcesResponse {
  projectId: string;
  projectTitle: string;
  projectSourceType: string;
  projectSourceReference: string;
  projectDescription?: string | null;
  sources: IngestedSource[];
}

export function SourceInspectionDialog({
  projectId,
  projectTitle,
  sourceReference,
  sourceType,
  isOpen,
  onClose,
}: SourceInspectionDialogProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SourcesResponse | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isOpen && projectId) {
      loadSources();
    } else {
      setData(null);
      setError(null);
      setSelectedIndex(0);
      setCopied(false);
    }
  }, [isOpen, projectId]);

  const loadSources = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await ProjectService.getProjectSources(projectId);
      setData(res);
      setSelectedIndex(0);
    } catch (err) {
      console.error("Failed to load source details:", err);
      setError(err instanceof Error ? err.message : "Failed to load source documents");
    } finally {
      setLoading(false);
    }
  };

  const currentSource: IngestedSource | undefined = data?.sources?.[selectedIndex];
  const hasExtractedText = Boolean(currentSource?.extractedText && currentSource.extractedText.trim().length > 0);

  const handleCopy = () => {
    const textToCopy = currentSource?.extractedText || data?.projectSourceReference || sourceReference;
    if (!textToCopy) return;
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    toast.success("Source text copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col p-6 overflow-hidden">
        <DialogHeader className="space-y-1.5 pb-2 border-b border-border/40">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-primary" />
            <DialogTitle className="text-lg font-semibold text-foreground">
              Source Inspection & Provenance
            </DialogTitle>
          </div>
          <DialogDescription className="text-xs text-muted-foreground">
            Original ingested source material for <span className="font-medium text-foreground">{projectTitle}</span>.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto py-4 space-y-4 pr-1">
          {/* Provenance & Mode Disclaimer Callout */}
          <div className="bg-muted/40 border border-border/50 rounded-xl p-3.5 text-xs space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <ShieldAlert className="w-4 h-4 text-primary" />
              <span>Canonical Ingested Source (Raw Input)</span>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              This panel displays the raw stored source material preserved in the database. In <strong>Demo Mode</strong>,
              embeddings are synthetic deterministic representations, live AI models are not invoked for indexing, and{" "}
              <strong>automated fact verification was not executed</strong>.
            </p>
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-xs text-muted-foreground">Retrieving stored source records...</p>
            </div>
          ) : error ? (
            <div className="bg-destructive/10 border border-destructive/20 rounded-xl p-4 text-xs space-y-2 text-destructive">
              <div className="flex items-center gap-2 font-medium">
                <AlertCircle className="w-4 h-4" />
                <span>Could not retrieve source document</span>
              </div>
              <p>{error}</p>
              <Button size="sm" variant="outline" onClick={loadSources} className="mt-2 text-xs">
                Retry
              </Button>
            </div>
          ) : (
            <>
              {/* Multi-source tabs if multiple sources exist */}
              {data && data.sources.length > 1 && (
                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                  <span className="text-xs text-muted-foreground font-medium shrink-0">Sources:</span>
                  {data.sources.map((src, idx) => (
                    <button
                      key={src.id}
                      onClick={() => setSelectedIndex(idx)}
                      className={`px-3 py-1 text-xs rounded-lg font-medium transition-colors border ${
                        selectedIndex === idx
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-muted/40 text-muted-foreground hover:bg-muted border-border/50"
                      }`}
                    >
                      {src.name || `Source ${idx + 1}`}
                    </button>
                  ))}
                </div>
              )}

              {/* Source Metadata Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-xl bg-card border border-border/50">
                  <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block mb-1">
                    Source Type
                  </span>
                  <span className="text-xs font-medium text-foreground">
                    {currentSource?.sourceType || data?.projectSourceType || sourceType || "Text Idea"}
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border/50">
                  <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block mb-1">
                    Ingestion Status
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        currentSource?.status === "completed"
                          ? "bg-emerald-500"
                          : currentSource?.status === "processing"
                          ? "bg-primary animate-pulse"
                          : currentSource?.status === "failed"
                          ? "bg-destructive"
                          : "bg-amber-500"
                      }`}
                    />
                    <span className="text-xs font-medium text-foreground capitalize">
                      {currentSource?.status || (data?.sources?.length === 0 ? "Not Ingested" : "Unknown")}
                    </span>
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border/50">
                  <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block mb-1">
                    Characters / Chunks
                  </span>
                  <span className="text-xs font-medium text-foreground">
                    {currentSource
                      ? `${(currentSource.charCount || 0).toLocaleString()} chars · ${currentSource.chunkCount || 0} chunks`
                      : "—"}
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border/50">
                  <span className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider block mb-1">
                    Date Ingested
                  </span>
                  <span className="text-xs font-medium text-foreground truncate block" title={currentSource?.createdAt || "N/A"}>
                    {currentSource?.createdAt ? new Date(currentSource.createdAt).toLocaleDateString() : "Initial Draft"}
                  </span>
                </div>
              </div>

              {/* Source URL if available */}
              {currentSource?.sourceUrl && (
                <div className="p-3 rounded-xl bg-card border border-border/50 flex items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <ExternalLink className="w-4 h-4 text-primary shrink-0" />
                    <span className="text-muted-foreground shrink-0">Source URL:</span>
                    <a
                      href={currentSource.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-primary hover:underline truncate"
                    >
                      {currentSource.sourceUrl}
                    </a>
                  </div>
                </div>
              )}

              {/* Content Container */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                    <FileText className="w-4 h-4 text-primary" />
                    <span>Stored Source Content</span>
                  </div>

                  <div className="flex items-center gap-2">
                    {hasExtractedText && (
                      <span className="text-[11px] text-muted-foreground">
                        {currentSource?.extractedText?.split(/\s+/).filter(Boolean).length} words
                      </span>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCopy}
                      className="h-7 px-2.5 text-xs flex items-center gap-1"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copied ? "Copied" : "Copy Text"}</span>
                    </Button>
                  </div>
                </div>

                {hasExtractedText ? (
                  <div className="max-h-[300px] overflow-y-auto p-4 rounded-xl bg-muted/40 font-mono text-xs text-foreground/90 border border-border/50 whitespace-pre-wrap select-text leading-relaxed break-words">
                    {currentSource?.extractedText}
                  </div>
                ) : data && data.sources.length > 0 ? (
                  /* Ingested document exists but has no extractable text */
                  <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400 space-y-2">
                    <div className="flex items-center gap-2 font-medium">
                      <Info className="w-4 h-4 shrink-0" />
                      <span>No extractable text stored for this document</span>
                    </div>
                    <p className="text-muted-foreground">
                      The source document record was created, but no plain text was extracted (e.g. image-only PDF or empty content).
                    </p>
                    {data.projectSourceReference && (
                      <div className="mt-2 pt-2 border-t border-amber-500/20 font-mono text-[11px] text-foreground/80">
                        Initial reference: {data.projectSourceReference}
                      </div>
                    )}
                  </div>
                ) : (
                  /* No source document record exists in storage */
                  <div className="p-4 rounded-xl bg-muted/30 border border-border/50 text-xs space-y-2">
                    <div className="flex items-center gap-2 font-medium text-foreground">
                      <Info className="w-4 h-4 text-primary shrink-0" />
                      <span>No dedicated source document in database</span>
                    </div>
                    <p className="text-muted-foreground">
                      No separate <code className="text-xs bg-muted px-1 py-0.5 rounded">SourceDocument</code> record was found for this project.
                      Displaying initial reference provided at project creation:
                    </p>
                    <div className="p-3 rounded-lg bg-background border border-border/50 font-mono text-xs whitespace-pre-wrap select-text">
                      {data?.projectSourceReference || sourceReference || "No reference recorded."}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <DialogFooter className="pt-2 border-t border-border/40">
          <Button variant="outline" size="sm" onClick={onClose} className="text-xs">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
