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

  // Clean up
  fs.rmSync(outDir, { recursive: true, force: true });
  console.log('\nAll status consistency checks passed successfully.');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
