#!/usr/bin/env node
// Checks the plain-language "Your Project Progress" panel: step count and labels come from the project's real
// stages, statuses match what the backend reported, the next action is unambiguous, human review stays mandatory,
// and no developer jargon is shown. Pure logic only: no network, no AI, no database.
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

function compile() {
  const ts = load('typescript');
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcf-orchestration-view-check-'));
  const program = ts.createProgram([path.join(SRC, 'lib/orchestration-view.ts')], {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true, skipLibCheck: true,
    outDir, rootDir: SRC, baseUrl: FRONTEND, paths: { '@/*': ['./src/*'] }, noEmitOnError: false, types: [],
  });
  const emitted = program.emit();
  const syntax = program.getSyntacticDiagnostics();
  if (emitted.emitSkipped || syntax.length) {
    throw new Error('Compilation failed:\n' + ts.formatDiagnostics(syntax, {
      getCanonicalFileName: (f) => f, getCurrentDirectory: () => FRONTEND, getNewLine: () => '\n' }));
  }
  const resolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    const target = request.startsWith('@/') ? path.join(outDir, request.slice(2)) : request;
    try { return resolve.call(this, target, parent, ...rest); } catch { return load.resolve(target); }
  };
  return outDir;
}

const outDir = compile();
const view = load(path.join(outDir, 'lib/orchestration-view.js'));
const { PRODUCT_STAGE_KEYS, buildSteps, summarize, plainMessage, friendlyStageLabel } = view;

let passed = 0;
function check(name, fn) {
  try { fn(); passed += 1; console.log(`  ok  ${name}`); } catch (e) { console.error(`  FAIL  ${name}\n${e.message}`); process.exitCode = 1; }
}

// A project with the real product-workflow stages (backend/app/core/workflow.py::PRODUCT_WORKFLOW_KEYS).
const stages = (done = []) => PRODUCT_STAGE_KEYS.map((type) => ({ type, label: type, status: done.includes(type) ? 'Completed' : 'Not Started' }));
const base = { projectId: 'p', status: 'in_progress', currentStage: 'source-grounding', sourcesGrounded: true };
const statusOf = (steps, key) => steps.find((s) => s.key === key).status;
const JARGON = /langgraph|orchestrat|pipeline|boundary|agent|embedding|\bRAG\b/i;

console.log('check-orchestration-panel');

check('shows exactly the project\'s real stages (8 for the product workflow), numbered 1..N', () => {
  const steps = buildSteps(stages(), null);
  assert.equal(PRODUCT_STAGE_KEYS.length, 8);
  assert.equal(steps.length, 8);
  assert.deepEqual(steps.map((s) => s.number), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(steps.map((s) => s.key), [...PRODUCT_STAGE_KEYS]);
  assert.equal(summarize(steps, null).total, 8);
});

check('only lists stages the project actually has; falls back to the full list when none are loaded', () => {
  const partial = stages().filter((s) => s.type !== 'content-type');
  assert.equal(buildSteps(partial, null).length, 7);
  assert.equal(buildSteps(undefined, null).length, 8);
  assert.equal(buildSteps([], null).length, 8);
});

check('stage labels are short and plain; unknown stages fall back to the backend label', () => {
  const labels = buildSteps(stages(), null).map((s) => s.label);
  assert.deepEqual(labels, ['Your Sources', 'Product Profile', 'Competitors', 'Promotion Strategy', 'Content Type', 'Write the Post', 'Quality Check', 'Final Review']);
  assert.equal(friendlyStageLabel('some-new-stage', 'Brand New Stage'), 'Brand New Stage');
  for (const l of labels) assert.ok(!JARGON.test(l), l);
});

check('not started: everything is "Not started" and one clear action is offered', () => {
  const steps = buildSteps(stages(), null);
  assert.ok(steps.every((s) => s.status === 'pending' && s.statusText === 'Not started'));
  const s = summarize(steps, null);
  assert.equal(s.primary.label, 'Start Workflow');
  assert.equal(s.primary.kind, 'run');
  assert.equal(s.doneCount, 0);
});

check('profile awaiting approval: that step "Needs your input", later steps not started, user is sent to the step', () => {
  const state = { ...base, status: 'halted', currentStage: 'product-understanding', haltReason: 'Product profile (version 1) requires human approval before proceeding.' };
  const steps = buildSteps(stages(['source-grounding']), state);
  assert.equal(statusOf(steps, 'source-grounding'), 'completed');
  assert.equal(statusOf(steps, 'product-understanding'), 'halted');
  assert.equal(steps.find((s) => s.key === 'product-understanding').statusText, 'Needs your input');
  assert.equal(statusOf(steps, 'competitor-analysis'), 'pending');
  const s = summarize(steps, state);
  assert.equal(s.tone, 'attention');
  assert.deepEqual({ kind: s.primary.kind, stage: s.primary.stage, label: s.primary.label }, { kind: 'goto', stage: 'product-understanding', label: 'Go to Product Profile' });
  assert.equal(s.secondary.label, 'Continue Workflow');
  assert.equal(s.doneCount, 1);
});

check('in progress between stages: "Up next" (nothing is claimed to be running) and Continue Workflow', () => {
  const state = { ...base, currentStage: 'competitor-analysis', profileApproved: true };
  const steps = buildSteps(stages(['source-grounding']), state);
  assert.equal(statusOf(steps, 'product-understanding'), 'completed');
  assert.equal(statusOf(steps, 'competitor-analysis'), 'active');
  assert.equal(steps.find((s) => s.key === 'competitor-analysis').statusText, 'Up next');
  const s = summarize(steps, state);
  assert.equal(s.primary.label, 'Continue Workflow');
  assert.match(s.description, /Competitors/);
});

check('waiting for review: review step is "Waiting for your review", not complete; approval is never automatic', () => {
  const state = { ...base, status: 'paused_at_approval_boundary', currentStage: 'review-approval', profileApproved: true, competitorsApproved: true,
    strategyApproved: true, contentVersion: 2, evaluationVersion: 2, evaluationCurrent: true, reviewApproved: false };
  const steps = buildSteps(stages(['source-grounding', 'content-type']), state);
  assert.equal(statusOf(steps, 'review-approval'), 'paused');
  assert.equal(statusOf(steps, 'evaluate-improve'), 'completed');
  assert.equal(statusOf(steps, 'generate-content'), 'completed');
  const s = summarize(steps, state);
  assert.equal(s.title, 'Waiting for Your Review');
  assert.equal(s.primary.label, 'Review & Approve Post');
  assert.equal(s.primary.stage, 'review-approval');
  assert.match(s.description, /approved or published without you/);
  assert.ok(s.doneCount < s.total, 'a pending review must not read as complete');
});

check('approved: all steps done, success message, nothing is published or scheduled automatically', () => {
  const state = { ...base, status: 'completed', currentStage: 'review-approval', reviewApproved: true, approvedVersion: 3, contentVersion: 3 };
  const steps = buildSteps(stages(), state);
  assert.ok(steps.every((s) => s.status === 'completed'));
  const s = summarize(steps, state);
  assert.equal(s.tone, 'success');
  assert.equal(s.doneCount, s.total);
  assert.match(s.title, /v3/);
  assert.match(s.description, /Nothing is published or scheduled automatically/);
  assert.equal(s.primary.label, 'View Approved Post');
});

check('errors: plain wording, saved work reassured, a retry action, and no stage is falsely marked done', () => {
  const state = { ...base, status: 'error', currentStage: 'generate-content', errors: ['x'], haltReason: 'Ingest product sources before running workflow orchestration.' };
  const s = summarize(buildSteps(stages(), state), state);
  assert.equal(s.tone, 'error');
  assert.equal(s.primary.label, 'Try Again');
  assert.ok(!JARGON.test(s.description), s.description);
  assert.match(s.description, /saved work is safe/);
  const loadError = summarize(buildSteps(stages(), null), null, { error: 'Network request failed' });
  assert.equal(loadError.tone, 'error');
});

check('loading: no action is offered while the status is being checked', () => {
  const s = summarize(buildSteps(stages(), null), null, { isLoading: true });
  assert.equal(s.tone, 'loading');
  assert.equal(s.primary, null);
});

check('content-type is completed by the workflow, not guessed from other fields', () => {
  const state = { ...base, currentStage: 'generate-content', profileApproved: true, competitorsApproved: true, strategyApproved: true };
  assert.equal(statusOf(buildSteps(stages(['content-type']), state), 'content-type'), 'completed');
  assert.equal(statusOf(buildSteps(stages(), state), 'content-type'), 'pending');
});

check('sources ingested but Source Grounding not yet completed: the panel agrees with the sidebar (not "Done")', () => {
  const state = { ...base, sourcesGrounded: true, status: 'in_progress', currentStage: 'source-grounding' };
  const rows = PRODUCT_STAGE_KEYS.map((type) => ({ type, label: type, status: type === 'source-grounding' ? 'Not Started' : 'Locked' }));
  const steps = buildSteps(rows, state);
  assert.equal(statusOf(steps, 'source-grounding'), 'active');
  assert.equal(summarize(steps, state).doneCount, 0);
  const completed = buildSteps(rows.map((r) => (r.type === 'source-grounding' ? { ...r, status: 'Completed' } : r)), state);
  assert.equal(statusOf(completed, 'source-grounding'), 'completed');
  assert.equal(summarize(completed, state).doneCount, 1);
});

check('content type waiting for approval is shown as needing input, and the user is sent to that step', () => {
  const state = { ...base, status: 'halted', currentStage: 'content-type', profileApproved: true, competitorsApproved: true, strategyApproved: true,
    haltReason: 'Approve a Content Type first. Content generation needs an approved Content Type for the current strategy.' };
  const steps = buildSteps(stages(['source-grounding']), state);
  assert.equal(statusOf(steps, 'content-type'), 'halted');
  assert.equal(statusOf(steps, 'generate-content'), 'pending');
  const s = summarize(steps, state);
  assert.equal(s.primary.stage, 'content-type');
  assert.equal(s.primary.label, 'Go to Content Type');
});

check('plainMessage removes internal vocabulary without changing the meaning', () => {
  assert.equal(plainMessage('Ingest product sources before running workflow orchestration.'), 'Ingest product sources before running the workflow.');
  assert.equal(plainMessage('LangGraph orchestration failed'), 'workflow workflow failed');
  assert.equal(plainMessage(null), '');
  assert.equal(plainMessage('  Product profile requires approval.  '), 'Product profile requires approval.');
});

check('every user-facing string in every state is free of developer jargon', () => {
  const cases = [
    [null, {}], [null, { isLoading: true }], [null, { error: 'boom' }],
    [{ ...base, status: 'halted', currentStage: 'competitor-analysis', haltReason: 'Competitor analysis requires human review and approval before promotion strategy.' }, {}],
    [{ ...base, status: 'paused_at_approval_boundary', currentStage: 'review-approval', contentVersion: 1 }, {}],
    [{ ...base, status: 'completed', reviewApproved: true, approvedVersion: 1 }, {}],
    [{ ...base, status: 'error', haltReason: 'x' }, {}], [{ ...base }, {}],
  ];
  for (const [state, opts] of cases) {
    const steps = buildSteps(stages(), state);
    const s = summarize(steps, state, opts);
    const text = [s.title, s.description, s.badge, s.primary?.label, s.secondary?.label, ...steps.flatMap((x) => [x.label, x.statusText])].join(' | ');
    assert.ok(!JARGON.test(text), text);
  }
});

check('panel source: no developer wording, accessible structure, existing navigation hooks are kept', () => {
  const source = fs.readFileSync(path.join(SRC, 'components/projects/orchestration-panel.tsx'), 'utf8');
  for (const old of ['LangGraph Orchestration Pipeline', 'Ready to Orchestrate', 'Auto-Orchestrate Pipeline',
    'Paused at Human Review Boundary', 'Orchestrating Pipeline', 'Prerequisite Stage Input Required', 'across all 6 stages']) {
    assert.ok(!source.includes(old), `still shows: ${old}`);
  }
  assert.ok(source.includes('Your Project Progress'));
  for (const needed of ['<ol', 'aria-current', 'role="progressbar"', 'role="status"', 'aria-live="polite"', 'focus-visible:ring-2', 'aria-labelledby']) {
    assert.ok(source.includes(needed), `missing accessibility feature: ${needed}`);
  }
  // Props, services and navigation used by workspace-content.tsx are unchanged.
  for (const kept of ['onSelectStage', 'onStateUpdate', 'onProjectRefresh', 'onRetry', 'WorkflowOrchestrationService.orchestrate(project.id)']) {
    assert.ok(source.includes(kept), `missing existing hook: ${kept}`);
  }
  assert.ok(source.includes('grid-cols-2 sm:grid-cols-4'), 'responsive grid');
});

check('strategy editor: concise key decisions up front, detail under a collapsed Advanced settings, every field still editable', () => {
  const source = fs.readFileSync(path.join(SRC, 'components/projects/stages/promotion-strategy-stage.tsx'), 'utf8');
  assert.ok(source.includes('What to review') && /Editing is optional/.test(source));
  assert.ok(source.includes('Advanced settings') && source.includes('aria-expanded={showAdvanced}') && source.includes('aria-controls="strategy-advanced-settings"'));
  assert.ok(source.includes('useState(false)') && source.includes('setShowAdvanced'), 'collapsed by default');
  const advancedStart = source.indexOf('id="strategy-advanced-settings"');
  const advancedEnd = source.indexOf('Evidence, assumptions & limitations');
  assert.ok(advancedStart > 0 && advancedEnd > advancedStart);
  const advanced = source.slice(advancedStart, advancedEnd);
  for (const detail of ['Channel priorities', 'Publishing cadence', 'Initial roadmap', 'Measurement plan']) {
    assert.ok(advanced.includes(detail), `${detail} lives under Advanced settings`);
  }
  const visible = source.slice(0, advancedStart);
  for (const key of ['Executive summary', 'Audience & positioning', 'Content pillars', 'Recommended content type']) {
    assert.ok(visible.includes(key), `${key} stays visible by default`);
  }
  // Nothing was removed: every editable control and every disclosure is still present.
  for (const kept of ['Messaging direction', 'Save Strategy', 'Approve Again', 'Cancel', 'Regenerate', 'Demo mode', 'Competitor Analysis changed',
    'Evidence, assumptions & limitations', 'Confirm Remove', "set(['roadmap', i, 'timing'])", "set(['measurement', i, 'indicator'])"]) {
    assert.ok(source.includes(kept), `missing: ${kept}`);
  }
});

console.log(`\n${passed} checks passed${process.exitCode ? ', some FAILED' : ''}`);
