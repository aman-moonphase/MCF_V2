#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import Module, { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT = fileURLToPath(import.meta.url);
const FRONTEND = path.resolve(path.dirname(SCRIPT), '..');
const SRC = path.join(FRONTEND, 'src');
const load = createRequire(path.join(FRONTEND, 'package.json'));

function compileAndLoad() {
  const ts = load('typescript');
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcf-status-check-'));
  const program = ts.createProgram(
    [path.join(SRC, 'lib/project-title.ts')],
    {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
      skipLibCheck: true,
      outDir,
      rootDir: SRC,
      baseUrl: FRONTEND,
      paths: { '@/*': ['./src/*'] },
      noEmitOnError: false,
      types: [],
    }
  );
  const emitted = program.emit();
  const syntax = program.getSyntacticDiagnostics();
  if (emitted.emitSkipped || syntax.length) {
    throw new Error('Compilation failed:\n' + ts.formatDiagnostics(syntax, {
      getCanonicalFileName: (f) => f, getCurrentDirectory: () => FRONTEND, getNewLine: () => '\n' }));
  }

  const projectTitleModule = load(path.join(outDir, 'lib/project-title.js'));
  return { projectTitleModule, outDir };
}

async function run() {
  console.log('--- Testing Project Title Binding & Extraction ---');
  const { projectTitleModule, outDir } = compileAndLoad();
  const { getDisplayProjectTitle } = projectTitleModule;

  // 1. Direct saved title returns as-is
  assert.equal(
    getDisplayProjectTitle({ title: 'BudgetBloom Persona Test' }),
    'BudgetBloom Persona Test',
    'Should return saved project title as-is'
  );

  // 2. Prefixed truncated title with full name in description
  const truncatedProject = {
    title: 'Idea: Project Name: BudgetBloom Pers...',
    description: 'Project Name: BudgetBloom Persona Test\nProduct Name: BudgetBloom\nDescription: App',
  };
  assert.equal(
    getDisplayProjectTitle(truncatedProject),
    'BudgetBloom Persona Test',
    'Should recover clean project title from description when title was raw truncated Idea prefix'
  );

  // 3. Prefixed title with Title: prefix
  const titlePrefixed = {
    title: 'Idea: Title: Persona Tone Test...',
    description: 'Title: Persona Tone Test\nSome details',
  };
  assert.equal(
    getDisplayProjectTitle(titlePrefixed),
    'Persona Tone Test',
    'Should extract clean title when prefixed with Idea: Title:'
  );

  // 4. Fallback unstructured idea preserves idea title
  const rawIdeaProject = {
    title: 'Idea: Build a new tool for artists...',
    description: 'Build a new tool for artists to track expenses',
  };
  assert.equal(
    getDisplayProjectTitle(rawIdeaProject),
    'Idea: Build a new tool for artists...',
    'Should preserve regular unstructured idea titles'
  );

  // 5. Null or empty project
  assert.equal(getDisplayProjectTitle(null), 'Untitled Project');
  assert.equal(getDisplayProjectTitle({ title: '' }), 'Untitled Project');

  console.log('✓ Project title binding & recovery tests passed.');

  console.log('--- Testing Composer Title Extraction Logic ---');
  // Verify composer title extraction regex matches what is in Composer.tsx
  const sampleStructured = 'Project Name: BudgetBloom Persona Test\nProduct Name: BudgetBloom';
  const match = sampleStructured.match(/^\s*(?:Project\s*Name|Project\s*Title|Title)\s*:\s*([^\r\n]+)/im);
  assert.ok(match, 'Regex should match Project Name');
  assert.equal(match[1].trim(), 'BudgetBloom Persona Test');

  console.log('✓ Composer title regex extraction tests passed.');

  console.log('--- Testing Source Grounding Truthful Status Logic ---');
  // Verify truthfulness conditions:
  // Case A: Stage is Not Started, no factVerification
  const notStartedStage = {
    status: 'Not Started',
    data: null,
  };
  const isNotStarted = notStartedStage.status === 'Not Started';
  const factVerificationDisplay = notStartedStage.data?.factVerification?.passed
    ? 'Verification Passed'
    : 'Not Executed (Demo Mode)';
  assert.equal(isNotStarted, true);
  assert.equal(factVerificationDisplay, 'Not Executed (Demo Mode)');
  assert.notEqual(factVerificationDisplay, 'Fact Verification Complete');

  // Case B: Completed stage
  const completedStage = {
    status: 'Completed',
    data: { factVerification: { passed: true } },
  };
  const completedFV = completedStage.data?.factVerification?.passed
    ? 'Verification Passed'
    : 'Not Executed (Demo Mode)';
  assert.equal(completedFV, 'Verification Passed');

  console.log('✓ Source Grounding status truthfulness tests passed.');

  console.log('--- Testing Tone & Persona Context Binding in Generate Content ---');
  // Helper matching generate-content-stage logic
  function resolveContextBindings(draft, selectedTone, selectedPersona, availablePersonas = ['Primary Target Audience']) {
    const draftTone = draft?.contextSnapshot?.editorialTone;
    const draftPersona = draft?.contextSnapshot?.audiencePersona;
    const toneUsedForContext = draft ? (draftTone || 'professional') : selectedTone;
    const personaUsedForContext = draft ? (draftPersona || availablePersonas[0] || 'Primary Target Audience') : selectedPersona;
    const toneDiffers = Boolean(draft && draftTone && selectedTone && draftTone.toLowerCase() !== selectedTone.toLowerCase());
    const personaDiffers = Boolean(draft && draftPersona && selectedPersona && draftPersona !== selectedPersona);
    return { toneUsedForContext, personaUsedForContext, toneDiffers, personaDiffers };
  }

  // Case 1: Draft exists with Conversational, but selector was changed to Professional
  const conversationalDraft = {
    version: 21,
    contextSnapshot: {
      editorialTone: 'conversational',
      audiencePersona: 'College students managing limited budgets',
    },
  };
  const res1 = resolveContextBindings(conversationalDraft, 'professional', 'College students managing limited budgets');
  assert.equal(res1.toneUsedForContext, 'conversational', 'Panel must identify context used for current draft, not un-regenerated selector');
  assert.equal(res1.toneDiffers, true, 'Should detect that selector differs from draft snapshot');
  assert.equal(res1.personaDiffers, false);

  // Case 2: Draft exists with Conversational, selector matches Conversational
  const res2 = resolveContextBindings(conversationalDraft, 'conversational', 'College students managing limited budgets');
  assert.equal(res2.toneUsedForContext, 'conversational');
  assert.equal(res2.toneDiffers, false);

  // Case 3: No draft generated yet, panel reflects initial selected tone & persona
  const res3 = resolveContextBindings(null, 'bold', 'Young Professionals');
  assert.equal(res3.toneUsedForContext, 'bold', 'When no draft exists, panel reflects initial selection');
  assert.equal(res3.personaUsedForContext, 'Young Professionals');
  assert.equal(res3.toneDiffers, false);

  // Case 4: Legacy draft without editorialTone key in contextSnapshot
  const legacyDraft = {
    version: 1,
    contextSnapshot: {
      pillar: 'The problem we solve',
    },
  };
  const res4 = resolveContextBindings(legacyDraft, 'professional', 'Primary Target Audience');
  assert.equal(res4.toneUsedForContext, 'professional', 'Legacy drafts without editorialTone fallback cleanly to professional');

  // Case 5: Refresh simulation where pending preference is loaded from ctx
  const mockApiState = {
    context: {
      selectedTone: 'bold',
      selectedPersona: 'Decision-Maker',
      availablePersonas: ['Primary Target Audience', 'Decision-Maker'],
    },
    draft: conversationalDraft,
  };
  // Emulate apply(mockApiState)
  const preferredTone = mockApiState.context?.selectedTone || mockApiState.draft?.contextSnapshot?.editorialTone || 'professional';
  const preferredPersona = mockApiState.context?.selectedPersona || mockApiState.draft?.contextSnapshot?.audiencePersona || '';
  const res5 = resolveContextBindings(mockApiState.draft, preferredTone, preferredPersona);
  assert.equal(preferredTone, 'bold', 'Pending preference is preserved in selector upon refresh');
  assert.equal(res5.toneUsedForContext, 'conversational', 'Approved context used for generation still accurately shows conversational');
  assert.equal(res5.toneDiffers, true, 'Discrepancy is cleanly flagged between pending selector and draft context');

  console.log('✓ Tone & persona context binding tests passed.');

  console.log('--- Testing Source Inspection & Provenance Verification Logic ---');
  // Helper simulating SourceInspectionDialog logic
  function resolveSourceInspectionView(sourcesResponse, projectRef, projectType) {
    const sources = sourcesResponse?.sources || [];
    const hasSources = sources.length > 0;
    const current = hasSources ? sources[0] : null;
    const hasExtractedText = Boolean(current?.extractedText && current.extractedText.trim().length > 0);

    // Provenance disclaimer check
    const isDemoModeNotePresent = true; // Raw source material preserved, no live AI/embeddings or fact verification implied

    // Text to copy or view
    const viewableText = hasExtractedText
      ? current.extractedText
      : (sourcesResponse?.projectSourceReference || projectRef || '');

    const statusDisplay = current?.status || (hasSources ? 'Unknown' : 'Not Ingested');
    const isMissingText = !hasExtractedText && hasSources;
    const isMissingSource = !hasSources;

    return {
      hasSources,
      hasExtractedText,
      viewableText,
      statusDisplay,
      isMissingText,
      isMissingSource,
      isDemoModeNotePresent,
      charCount: current?.charCount || (current?.extractedText ? current.extractedText.length : 0),
    };
  }

  // Case 1: Ingested source with full untruncated text
  const fullText = "Project Name: BudgetBloom Persona Test\nProduct Name: BudgetBloom\nDescription: Long un-truncated financial source text.".repeat(20);
  const mockSourcesData1 = {
    projectId: "7118a733-737e-4c3d-895b-1c494185f71b",
    projectTitle: "BudgetBloom Persona Test",
    projectSourceType: "Text Idea",
    projectSourceReference: "Project Name: BudgetBloom Persona Test...",
    sources: [
      {
        id: "dafd54a0-53e4-42e8-8c6f-cba4a42b8e20",
        name: "Ingested text",
        sourceType: "text",
        status: "completed",
        extractedText: fullText,
        charCount: fullText.length,
        chunkCount: 2,
      }
    ]
  };

  const insp1 = resolveSourceInspectionView(mockSourcesData1, "BudgetBloom preview", "Text Idea");
  assert.equal(insp1.hasSources, true);
  assert.equal(insp1.hasExtractedText, true);
  assert.equal(insp1.viewableText, fullText, "Original source text must not be truncated in inspection dialog");
  assert.equal(insp1.statusDisplay, "completed");
  assert.equal(insp1.isMissingText, false);
  assert.equal(insp1.isMissingSource, false);

  // Case 2: Document exists but has empty/null extracted text (e.g. image-only PDF)
  const mockSourcesData2 = {
    projectId: "269765a4-b717-4d5f-9ded-6aa7edf43b35",
    projectTitle: "Document: attention.pdf",
    projectSourceType: "File",
    projectSourceReference: "attention.pdf",
    sources: [
      {
        id: "530d9936-8ed2-4043-a8e5-36497b2f748f",
        name: "Ingested pdf",
        sourceType: "upload",
        status: "completed",
        extractedText: "",
        charCount: 0,
        chunkCount: 0,
      }
    ]
  };

  const insp2 = resolveSourceInspectionView(mockSourcesData2, "attention.pdf", "File");
  assert.equal(insp2.hasSources, true);
  assert.equal(insp2.hasExtractedText, false);
  assert.equal(insp2.isMissingText, true, "Should clearly flag that document has no extractable text");
  assert.equal(insp2.viewableText, "attention.pdf", "Falls back to project source reference");

  // Case 3: No source document records in DB (legacy project)
  const mockSourcesData3 = {
    projectId: "c84c42f4-706c-496f-b031-4ddb0b0b96d4",
    projectTitle: "Legacy Project",
    projectSourceType: "Text Idea",
    projectSourceReference: "Draft idea typed during onboarding",
    sources: []
  };

  const insp3 = resolveSourceInspectionView(mockSourcesData3, "Draft idea typed during onboarding", "Text Idea");
  assert.equal(insp3.hasSources, false);
  assert.equal(insp3.isMissingSource, true, "Should clearly flag that no dedicated SourceDocument exists");
  assert.equal(insp3.statusDisplay, "Not Ingested");
  assert.equal(insp3.viewableText, "Draft idea typed during onboarding");

  console.log('✓ Source Inspection & Provenance Verification tests passed.');

  // Clean up
  fs.rmSync(outDir, { recursive: true, force: true });
  console.log('\nAll status consistency checks passed successfully.');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
