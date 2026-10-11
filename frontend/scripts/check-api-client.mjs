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

function compile() {
  const ts = load('typescript');
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcf-api-client-check-'));
  const program = ts.createProgram(
    [path.join(SRC, 'lib/api-client.ts'), path.join(SRC, 'lib/api-errors.ts')],
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

  const resolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    let target = request;
    if (request.startsWith('@/')) target = path.join(outDir, request.slice(2));
    try {
      return resolve.call(this, target, parent, ...rest);
    } catch {
      return load.resolve(target);
    }
  };

  return outDir;
}

const outDir = compile();
const { convertKeysToCamelCase, convertKeysToSnakeCase } = load(path.join(outDir, 'lib/api-client.js'));

// 1. Regression test: undefined value passed in object (FocusFlow trigger bug)
assert.doesNotThrow(() => {
  const result = convertKeysToSnakeCase({
    pillarIndex: 0,
    campaignInstructions: undefined,
  });
  assert.equal(result.pillar_index, 0);
  assert.equal(result.campaign_instructions, undefined);
}, 'convertKeysToSnakeCase must not throw on undefined properties');

// 2. Direct undefined argument
assert.doesNotThrow(() => {
  const res = convertKeysToSnakeCase(undefined);
  assert.equal(res, undefined);
}, 'convertKeysToSnakeCase(undefined) must safely return undefined');

assert.doesNotThrow(() => {
  const res = convertKeysToCamelCase(undefined);
  assert.equal(res, undefined);
}, 'convertKeysToCamelCase(undefined) must safely return undefined');

// 3. Null argument
assert.equal(convertKeysToSnakeCase(null), null);
assert.equal(convertKeysToCamelCase(null), null);

// 4. Primitive arguments
assert.equal(convertKeysToSnakeCase(42), 42);
assert.equal(convertKeysToSnakeCase('test'), 'test');
assert.equal(convertKeysToSnakeCase(true), true);

// 5. Nested objects and arrays containing undefined
const complexInput = {
  firstKey: 'hello',
  nestedObject: {
    secondKey: undefined,
    thirdKey: null,
    arrayItems: [1, undefined, { deepKey: 'world' }],
  },
};

const snakeResult = convertKeysToSnakeCase(complexInput);
assert.equal(snakeResult.first_key, 'hello');
assert.equal(snakeResult.nested_object.third_key, null);
assert.equal(snakeResult.nested_object.second_key, undefined);
assert.equal(snakeResult.nested_object.array_items[2].deep_key, 'world');

const camelResult = convertKeysToCamelCase(snakeResult);
assert.equal(camelResult.firstKey, 'hello');
assert.equal(camelResult.nestedObject.thirdKey, null);
assert.equal(camelResult.nestedObject.arrayItems[2].deepKey, 'world');

console.log('API client constructor/undefined regression check: passed');
