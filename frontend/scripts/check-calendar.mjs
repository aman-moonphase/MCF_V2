#!/usr/bin/env node
/*
 * Calendar regression checks — `npm run check:calendar`.
 *
 * Uses only tooling already in the project (the TypeScript compiler API, react-dom/server, node:assert); no test
 * framework. The calendar modules are compiled to a temporary directory and rendered to static HTML.
 *
 *  1. Month grid: every date of the month renders (also with no entries — the bug where a mobile month view showed
 *     no dates), adjacent-month days are muted, the grid is not hidden on narrow screens, entries are counted.
 *  2. Agenda list: compact empty note, nothing while loading, day sections with entries.
 *  3. Ranges in several time zones (child processes): local-midnight boundaries, [start, end), DST days of 23/25 h.
 *  4. Planning (Step 7): wall-clock time in a named zone → ISO instant with that date's offset (DST gap refused,
 *     overlap flagged), and the planning service: request shape, refusal reasons passed through, error kinds.
 *  5. Reschedule / cancel (Step 8): card actions per entry kind, lock_version on the wire, conflicts surfaced and
 *     never retried, error kinds, local refusals that send nothing, and the prefill helper.
 *  6. Preferences (Step 10): the settings service used for the calendar's default view and the planning defaults.
 *  7. Session rule (Step 11): only a server rejection (401/403) ends the session, not an outage.
 *
 * No network, no API calls, no data.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import Module, { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT = fileURLToPath(import.meta.url);
const FRONTEND = path.resolve(path.dirname(SCRIPT), '..');
const SRC = path.join(FRONTEND, 'src');
const ZONE_ARG = '--zone=';
const OUT_ARG = '--out=';
// The compiled calendar modules are CommonJS; load them (and packages) relative to the frontend.
const load = createRequire(path.join(FRONTEND, 'package.json'));

const NEXT_LINK_STUB = [
  "const React = require('react');",
  "module.exports = { __esModule: true, default: ({ href, children, ...rest }) => React.createElement('a', { href, ...rest }, children) };",
  '',
].join('\n');

function compile() {
  const ts = load('typescript');
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcf-calendar-check-'));
  const program = ts.createProgram(
    [path.join(SRC, 'components/calendar/month-grid.tsx'), path.join(SRC, 'components/calendar/agenda-list.tsx'),
     path.join(SRC, 'lib/calendar-range.ts'), path.join(SRC, 'lib/calendar-time.ts'),
     path.join(SRC, 'lib/services/schedule.service.ts'), path.join(SRC, 'components/calendar/calendar-entry-card.tsx'),
     path.join(SRC, 'lib/services/settings.service.ts')],
    {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
      skipLibCheck: true, outDir, rootDir: SRC, baseUrl: FRONTEND, paths: { '@/*': ['./src/*'] }, noEmitOnError: false,
      types: [],
    },
  );
  const emitted = program.emit();
  const syntax = program.getSyntacticDiagnostics();
  if (emitted.emitSkipped || syntax.length) {
    throw new Error('Compilation failed:\n' + ts.formatDiagnostics(syntax, {
      getCanonicalFileName: (f) => f, getCurrentDirectory: () => FRONTEND, getNewLine: () => '\n' }));
  }
  // next/link needs the Next.js runtime; a plain anchor is enough for static markup.
  fs.writeFileSync(path.join(outDir, '__next_link_stub.js'), NEXT_LINK_STUB);
  installResolver(outDir);
  return outDir;
}

/** Resolve "@/..." to the compiled output, next/link to the stub, and packages from frontend/node_modules. */
function installResolver(outDir) {
  const resolve = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    let target = request;
    if (request === 'next/link') target = path.join(outDir, '__next_link_stub.js');
    else if (request.startsWith('@/')) target = path.join(outDir, request.slice(2));
    try {
      return resolve.call(this, target, parent, ...rest);
    } catch {
      return load.resolve(target);  // bare packages live in frontend/node_modules
    }
  };
}

function entry(overrides) {
  return {
    id: 'e1', projectId: 'p1', projectTitle: 'CareNest launch', productId: null, productName: null,
    scheduledAt: '2026-10-22T03:30:00Z', scheduledAtLocal: null, timezone: null, platform: 'LinkedIn', notes: null,
    status: 'Scheduled', isLegacy: true, contentType: null, generatedContentId: null, contentVersion: null,
    contentDigest: null, currentContentStatus: null, currentContentVersion: null, lockVersion: 1, cancelledAt: null,
    createdAt: null, updatedAt: null, conditions: [], ...overrides,
  };
}

function componentChecks(outDir) {
  const React = load('react');
  const { renderToStaticMarkup } = load('react-dom/server');
  const { MonthGrid } = load(path.join(outDir, 'components/calendar/month-grid.js'));
  const { AgendaList } = load(path.join(outDir, 'components/calendar/agenda-list.js'));
  const r = load(path.join(outDir, 'lib/calendar-range.js'));
  const tz = 'Asia/Kolkata';
  const anchor = new Date(2026, 9, 10);
  const range = r.calendarRange('month', anchor);
  const noop = () => {};
  const grid = (byDay) => renderToStaticMarkup(React.createElement(MonthGrid, {
    days: range.days, anchor, timeZone: tz, byDay, onSelectDay: noop, onAddLegacy: noop }));

  // 1. Empty month: every date is rendered.
  const empty = grid(new Map());
  const days = [...empty.matchAll(/data-day="(\d{4}-\d{2}-\d{2})" data-outside="(true|false)"/g)];
  assert.equal(days.length, 35, 'October 2026 grid has 5 whole weeks');
  const inMonth = days.filter(([, , outside]) => outside === 'false').map(([, key]) => key);
  assert.deepEqual(inMonth, Array.from({ length: 31 }, (_, i) => `2026-10-${String(i + 1).padStart(2, '0')}`));
  assert.deepEqual(days.filter(([, , o]) => o === 'true').map(([, k]) => k), ['2026-09-27', '2026-09-28', '2026-09-29', '2026-09-30']);
  assert.match(empty, /aria-label="Thursday 22 October 2026, nothing planned"/);
  assert.equal((empty.match(/, nothing planned"/g) || []).length, 35);
  // The grid itself is never hidden at narrow widths (the regression), and adjacent-month cells are muted.
  const gridTag = empty.match(/<div class="([^"]*)" data-testid="month-grid"/);
  assert.ok(gridTag, 'month grid container');
  const gridClasses = gridTag[1].split(/\s+/);
  assert.ok(gridClasses.includes('grid-cols-7') && !gridClasses.includes('hidden'), gridTag[1]);
  const outsideCell = empty.match(/data-day="2026-09-27" data-outside="true" class="([^"]*)"/);
  assert.ok(outsideCell && outsideCell[1].includes('opacity-50'), 'adjacent-month day is muted');
  // Day numbers are buttons, readable on narrow screens (text-sm there).
  assert.match(empty, /<button type="button" aria-label="Saturday 31 October 2026, nothing planned" class="[^"]*text-sm[^"]*">31<\/button>/);

  // 2. Entries are counted on their local day (03:30Z on the 22nd is 09:00 in Kolkata).
  const withEntries = grid(new Map([['2026-10-22', [entry(), entry({ id: 'e2', conditions: ['date_passed'] })]]]));
  assert.match(withEntries, /aria-label="Thursday 22 October 2026, 2 entries"/);
  assert.match(withEntries, /CareNest launch/);
  assert.equal((withEntries.match(/data-day=/g) || []).length, 35, 'entries never remove dates');
  assert.equal(r.instantDayKey('2026-10-22T03:30:00Z', tz), '2026-10-22');
  assert.equal(r.instantDayKey('2026-10-21T19:00:00Z', tz), '2026-10-22');  // 00:30 local on the 22nd

  // 3. Agenda list: compact note, nothing while loading, sections with entries.
  const agenda = (byDay, emptyText) => renderToStaticMarkup(React.createElement(AgendaList, {
    days: r.calendarRange('week', new Date(2026, 9, 22)).days, timeZone: tz, byDay, emptyText }));
  assert.match(agenda(new Map(), 'Nothing planned for 18 – 24 Oct 2026.'), /data-testid="agenda-empty"[^>]*>Nothing planned for 18 – 24 Oct 2026\.</);
  assert.equal(agenda(new Map(), ''), '');
  const listed = agenda(new Map([['2026-10-22', [entry()]]]), 'unused');
  assert.match(listed, /aria-label="Thursday 22 October 2026"/);
  assert.doesNotMatch(listed, /agenda-empty/);
  console.log('components: OK (month grid always renders 35 dates; agenda empty/loading/listed states)');
}

/** Step 7: wall-clock time in a named zone → exact ISO instant (independent of the process zone). */
function zonedTimeChecks(outDir) {
  const t = load(path.join(outDir, 'lib/calendar-time.js'));
  const kolkata = t.zonedDateTimeToIso('2027-05-04', '10:30', 'Asia/Kolkata');
  assert.deepEqual([kolkata.iso, kolkata.offset, kolkata.ambiguous], ['2027-05-04T10:30:00+05:30', '+05:30', false]);
  assert.equal(kolkata.instantMs, Date.UTC(2027, 4, 4, 5, 0));
  assert.equal(t.zonedDateTimeToIso('2027-07-06', '09:00', 'America/New_York').iso, '2027-07-06T09:00:00-04:00');  // EDT
  assert.equal(t.zonedDateTimeToIso('2027-01-12', '09:00', 'America/New_York').iso, '2027-01-12T09:00:00-05:00');  // EST
  assert.equal(t.zonedDateTimeToIso('2027-01-12', '09:00', 'UTC').iso, '2027-01-12T09:00:00+00:00');
  // Spring forward in London (01:00 → 02:00): 01:30 does not exist.
  assert.throws(() => t.zonedDateTimeToIso('2027-03-28', '01:30', 'Europe/London'), /does not exist/);
  assert.equal(t.zonedDateTimeToIso('2027-03-28', '02:00', 'Europe/London').iso, '2027-03-28T02:00:00+01:00');
  // Fall back (02:00 → 01:00): 01:30 happens twice; the first occurrence (BST) is used and flagged.
  const overlap = t.zonedDateTimeToIso('2027-10-31', '01:30', 'Europe/London');
  assert.deepEqual([overlap.iso, overlap.ambiguous, overlap.instantMs], ['2027-10-31T01:30:00+01:00', true, Date.UTC(2027, 9, 31, 0, 30)]);
  for (const [d, h, z] of [['2027-02-30', '09:00', 'UTC'], ['2027-02-10', '24:00', 'UTC'], ['2027-02-10', '09:00', 'Mars/Base'],
                           ['', '09:00', 'UTC'], ['2027-02-10', '', 'UTC'], ['2027-02-10', '09:00', '']]) {
    assert.throws(() => t.zonedDateTimeToIso(d, h, z), t.InstantError, `${d} ${h} ${z}`);
  }
  assert.equal(t.formatOffset(-16200000), '-04:30');
  assert.equal(t.formatOffset(0), '+00:00');
  console.log('zoned times: OK (offset per date, DST gap refused, overlap flagged)');
}

/** Step 7: the planning service — request shape, error kinds, server reasons passed through, nothing sent if invalid. */
async function planningServiceChecks(outDir) {
  const { ScheduleService, PlanningApiError } = load(path.join(outDir, 'lib/services/schedule.service.js'));
  const calls = [];
  let reply = null;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const respond = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body });
  const request = { scheduledAt: '2027-05-04T10:30:00+05:30', timezone: 'Asia/Kolkata', platform: 'LinkedIn', notes: '  Launch  ', productId: 'prod-1' };
  const expectError = async (kind, status, codes) => {
    const error = await ScheduleService.planPost('proj-1', request).then(() => null, (e) => e);
    assert.ok(error instanceof PlanningApiError, `expected PlanningApiError, got ${error}`);
    assert.equal(error.kind, kind);
    assert.equal(error.status, status);
    assert.deepEqual(error.reasons.map((r) => r.code), codes);
    return error;
  };
  try {
    reply = respond(201, { id: 's1', project_id: 'proj-1', status: 'planned', scheduled_at: '2027-05-04T05:00:00Z', timezone: 'Asia/Kolkata',
      content_version: 3, lock_version: 1 });
    const entry = await ScheduleService.planPost('proj-1', request);
    assert.equal(calls.length, 1);
    assert.equal(new URL(calls[0].url).pathname, '/api/projects/proj-1/generated-content/schedule');
    assert.equal(calls[0].init.method, 'POST');
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      scheduled_at: '2027-05-04T10:30:00+05:30', timezone: 'Asia/Kolkata', platform: 'LinkedIn', notes: 'Launch', product_id: 'prod-1' });
    assert.ok(!('status' in JSON.parse(calls[0].init.body)), 'the status is never sent');
    assert.deepEqual([entry.status, entry.contentVersion, entry.scheduledAt], ['planned', 3, '2027-05-04T05:00:00Z']);

    const refusal = (code, message) => ({ detail: { message: 'This post cannot be planned.', reasons: [{ code, message }] } });
    reply = respond(409, refusal('evaluation_missing', 'Evaluate the saved post (version 1) first.'));
    const refused = await expectError('refused', 409, ['evaluation_missing']);
    assert.equal(refused.reasons[0].message, 'Evaluate the saved post (version 1) first.');
    reply = respond(409, refusal('duplicate_plan', 'Already planned.'));
    await expectError('refused', 409, ['duplicate_plan']);
    reply = respond(422, refusal('time_in_past', 'The planned time must be in the future.'));
    await expectError('validation', 422, ['time_in_past']);
    reply = respond(422, refusal('invalid_timezone', 'Choose a valid IANA time zone.'));
    await expectError('validation', 422, ['invalid_timezone']);
    reply = respond(422, { detail: [{ loc: ['body', 'scheduled_at'], msg: 'Input should be a valid datetime', type: 'x' }] });
    await expectError('validation', 422, []);
    reply = respond(404, { detail: { message: 'Project not found.', reasons: [{ code: 'project_not_found', message: 'Project not found.' }] } });
    await expectError('not_found', 404, ['project_not_found']);
    reply = respond(401, { detail: 'Not authenticated' });
    await expectError('auth', 401, []);
    reply = respond(500, { detail: 'boom' });
    await expectError('server', 500, []);
    reply = new TypeError('Failed to fetch');
    const network = await expectError('network', undefined, []);
    assert.match(network.message, /Nothing was saved/);

    // An instant without an offset is refused before anything is sent.
    calls.length = 0;
    const local = await ScheduleService.planPost('proj-1', { ...request, scheduledAt: '2027-05-04T10:30:00' }).then(() => null, (e) => e);
    assert.ok(local instanceof PlanningApiError && local.kind === 'validation');
    assert.equal(calls.length, 0);

    // Read-only eligibility: GET, reasons passed through unchanged.
    reply = respond(200, { eligible: false, reasons: [{ code: 'evaluation_missing', message: 'Evaluate first.' }], project_id: 'proj-1',
      product_id: null, generated_content_id: 'g1', content_type: 'Social Post', platform: 'linkedin', content_version: 1, evaluation_id: null });
    const eligibility = await ScheduleService.getPlanEligibility('proj-1');
    assert.equal(new URL(calls[0].url).pathname, '/api/projects/proj-1/generated-content/schedule/eligibility');
    assert.equal(calls[0].init?.method ?? 'GET', 'GET');
    assert.deepEqual([eligibility.eligible, eligibility.contentVersion, eligibility.reasons[0].code], [false, 1, 'evaluation_missing']);
  } finally {
    globalThis.fetch = realFetch;
  }
  console.log('planning service: OK (request shape, refusals passed through, error kinds, nothing sent when invalid)');
}

/** Step 8: which actions an entry card offers (planned vs legacy vs cancelled), in full and compact layouts. */
function cardActionChecks(outDir) {
  const React = load('react');
  const { renderToStaticMarkup } = load('react-dom/server');
  const { CalendarEntryCard } = load(path.join(outDir, 'components/calendar/calendar-entry-card.js'));
  const { MonthGrid } = load(path.join(outDir, 'components/calendar/month-grid.js'));
  const r = load(path.join(outDir, 'lib/calendar-range.js'));
  const noop = () => {};
  const handlers = { onEditLegacy: noop, onDeleteLegacy: noop, onReschedule: noop, onCancelPlan: noop };
  const card = (e, compact = false) => renderToStaticMarkup(React.createElement(CalendarEntryCard, { entry: e, timeZone: 'Asia/Kolkata', compact, ...handlers }));
  const planned = entry({ id: 'p1', isLegacy: false, status: 'planned', generatedContentId: 'g1', contentVersion: 2, contentDigest: 'a'.repeat(64),
    timezone: 'Asia/Kolkata', contentType: 'Social Post', lockVersion: 3 });
  for (const compact of [false, true]) {
    const html = card(planned, compact);
    assert.match(html, /aria-label="Reschedule plan for CareNest launch"/);
    assert.match(html, /aria-label="Cancel plan for CareNest launch"/);
    assert.doesNotMatch(html, /legacy entry for/, 'planned entries never get legacy edit/delete');
    assert.doesNotMatch(html, /View only/);
  }
  assert.match(card(planned), />Reschedule</);  // labelled buttons in full cards (day view, mobile agenda)
  for (const compact of [false, true]) {
    const legacyHtml = card(entry(), compact);
    assert.match(legacyHtml, /aria-label="Edit legacy entry for CareNest launch"/);
    assert.doesNotMatch(legacyHtml, /Reschedule plan for|Cancel plan for/, 'legacy entries never get planned-entry actions');
    const cancelledHtml = card({ ...planned, status: 'cancelled', cancelledAt: '2026-10-10T00:00:00Z' }, compact);
    assert.doesNotMatch(cancelledHtml, /Reschedule plan for|Cancel plan for|legacy entry for/, 'cancelled plans have no actions');
    assert.match(cancelledHtml, /Status: <\/span>cancelled/);  // the stored status, as stored
  }
  // The month grid passes the actions through to its cards.
  const range = r.calendarRange('month', new Date(2026, 9, 10));
  const grid = renderToStaticMarkup(React.createElement(MonthGrid, {
    days: range.days, anchor: new Date(2026, 9, 10), timeZone: 'Asia/Kolkata', onSelectDay: noop,
    byDay: new Map([['2026-10-22', [planned, entry({ id: 'l1' })]]]), ...handlers }));
  assert.equal((grid.match(/Reschedule plan for/g) || []).length, 1);
  assert.equal((grid.match(/Edit legacy entry for/g) || []).length, 1);
  // Step 9 regression: compact-card actions must stay keyboard-reachable (never display:none) and appear on focus,
  // hover and touch screens; full cards show them inline.
  for (const e of [planned, entry()]) {
    const bar = card(e, true).match(/<div data-testid="entry-actions" class="([^"]*)"/);
    assert.ok(bar, 'compact action toolbar');
    const classes = bar[1].split(/\s+/);
    assert.ok(!classes.includes('hidden'), `compact actions must not be display:none: ${bar[1]}`);
    for (const required of ['opacity-0', 'group-focus-within:opacity-100', 'group-hover:opacity-100', '[@media(hover:none)]:opacity-100',
                            'pointer-events-none', 'group-focus-within:pointer-events-auto']) {
      assert.ok(classes.includes(required), `compact actions need ${required}`);
    }
  }
  const fullBar = card(planned).match(/<div data-testid="entry-actions" class="([^"]*)"/)[1].split(/\s+/);
  assert.ok(!fullBar.includes('opacity-0') && !fullBar.includes('hidden'), 'full cards show their actions');
  // Step 9 regression: on the narrow month grid a cancelled plan's dot is distinct from an active one.
  const dots = renderToStaticMarkup(React.createElement(MonthGrid, {
    days: range.days, anchor: new Date(2026, 9, 10), timeZone: 'Asia/Kolkata', onSelectDay: noop,
    byDay: new Map([['2026-10-12', [{ ...planned, id: 'c1', status: 'cancelled', cancelledAt: '2026-10-10T18:24:12Z' },
                                     { ...planned, id: 'a1', conditions: [] }, { ...planned, id: 'w1', conditions: ['date_passed'] }]]]) }));
  assert.deepEqual([...dots.matchAll(/data-dot="(\w+)"/g)].map((m) => m[1]), ['cancelled', 'active', 'attention']);
  console.log('entry cards: OK (planned → Reschedule/Cancel plan; legacy → legacy actions only; cancelled → none; compact actions focusable; cancelled dots distinct)');
}

/** Step 8: reschedule / cancel / reload service contracts (mocked fetch) and the prefill helper. */
async function rescheduleCancelChecks(outDir) {
  const { ScheduleService, PlanningApiError } = load(path.join(outDir, 'lib/services/schedule.service.js'));
  const t = load(path.join(outDir, 'lib/calendar-time.js'));
  assert.deepEqual(t.zonedParts('2027-05-04T05:00:00Z', 'Asia/Kolkata'), { date: '2027-05-04', time: '10:30' });
  assert.deepEqual(t.zonedParts('2027-07-06T13:00:00Z', 'America/New_York'), { date: '2027-07-06', time: '09:00' });
  assert.deepEqual(t.zonedParts('2027-10-30T23:30:00Z', 'Europe/London'), { date: '2027-10-31', time: '00:30' });

  const calls = [];
  let reply = null;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const respond = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body });
  const refusal = (code, extra = {}) => ({ detail: { message: 'Refused.', reasons: [{ code, message: `${code} message` }], ...extra } });
  const fails = async (promise) => promise.then(() => assert.fail('expected a PlanningApiError'), (e) => {
    assert.ok(e instanceof PlanningApiError, String(e));
    return e;
  });
  try {
    // Reschedule: PATCH with lock_version + time + zone + notes (snake_case on the wire).
    reply = respond(200, { id: 's1', status: 'planned', lock_version: 4, scheduled_at: '2027-05-05T04:30:00Z', timezone: 'Asia/Kolkata' });
    const updated = await ScheduleService.reschedulePlan('s1', { lockVersion: 3, scheduledAt: '2027-05-05T10:00:00+05:30', timezone: 'Asia/Kolkata', notes: ' Moved ' });
    assert.equal(calls[0].init.method, 'PATCH');
    assert.equal(new URL(calls[0].url).pathname, '/api/schedules/s1');
    assert.deepEqual(JSON.parse(calls[0].init.body), { lock_version: 3, scheduled_at: '2027-05-05T10:00:00+05:30', timezone: 'Asia/Kolkata', notes: 'Moved' });
    assert.deepEqual([updated.lockVersion, updated.status], [4, 'planned']);
    // Notes only (and clearing them) send no time; nothing else is ever sent (no status, platform or content fields).
    await ScheduleService.reschedulePlan('s1', { lockVersion: 4, notes: 'Only notes' });
    assert.deepEqual(JSON.parse(calls[1].init.body), { lock_version: 4, notes: 'Only notes' });
    await ScheduleService.reschedulePlan('s1', { lockVersion: 5, notes: null });
    assert.deepEqual(JSON.parse(calls[2].init.body), { lock_version: 5, notes: null });

    // Conflict: refused, with the server's current version; the client never retries on its own.
    calls.length = 0;
    reply = respond(409, refusal('lock_conflict', { lock_version: 7 }));
    const conflict = await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 6, notes: 'x' }));
    assert.ok(conflict.hasCode('lock_conflict') && conflict.kind === 'refused' && conflict.currentLockVersion === 7);
    assert.equal(calls.length, 1, 'no automatic retry');
    reply = respond(409, refusal('content_changed'));
    assert.ok((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).hasCode('content_changed'));
    reply = respond(409, refusal('cancelled'));
    assert.ok((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).hasCode('cancelled'));
    reply = respond(422, refusal('time_in_past'));
    const past = await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, scheduledAt: '2020-01-01T09:00:00+05:30', timezone: 'Asia/Kolkata' }));
    assert.ok(past.kind === 'validation' && past.hasCode('time_in_past'));
    reply = respond(422, refusal('invalid_timezone'));
    assert.ok((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, scheduledAt: '2030-01-01T09:00:00+00:00', timezone: 'Mars/Base' }))).hasCode('invalid_timezone'));
    reply = respond(404, { detail: 'Schedule not found' });
    assert.equal((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).kind, 'not_found');
    reply = respond(403, { detail: 'Forbidden' });
    assert.equal((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).kind, 'auth');
    reply = respond(503, { detail: 'down' });
    assert.equal((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).kind, 'server');
    reply = new TypeError('Failed to fetch');
    assert.equal((await fails(ScheduleService.reschedulePlan('s1', { lockVersion: 7, notes: 'x' }))).kind, 'network');

    // Refused locally, nothing sent: missing lock version, time without zone, time without offset.
    calls.length = 0;
    for (const bad of [{ notes: 'x' }, { lockVersion: 0, notes: 'x' }, { lockVersion: 2, scheduledAt: '2030-01-01T09:00:00+05:30' },
                       { lockVersion: 2, scheduledAt: '2030-01-01T09:00:00', timezone: 'Asia/Kolkata' }]) {
      assert.equal((await fails(ScheduleService.reschedulePlan('s1', bad))).kind, 'validation');
    }
    assert.equal(calls.length, 0);

    // Cancel: POST …/cancel with lock_version; conflict surfaces the current version; local refusal sends nothing.
    reply = respond(200, { id: 's1', status: 'cancelled', cancelled_at: '2026-10-10T10:00:00Z', lock_version: 8 });
    const cancelled = await ScheduleService.cancelPlan('s1', 7);
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(new URL(calls[0].url).pathname, '/api/schedules/s1/cancel');
    assert.deepEqual(JSON.parse(calls[0].init.body), { lock_version: 7 });
    assert.deepEqual([cancelled.status, cancelled.lockVersion], ['cancelled', 8]);
    reply = respond(409, refusal('lock_conflict', { lock_version: 9 }));
    assert.equal((await fails(ScheduleService.cancelPlan('s1', 8))).currentLockVersion, 9);
    calls.length = 0;
    assert.equal((await fails(ScheduleService.cancelPlan('s1', 0))).kind, 'validation');
    assert.equal(calls.length, 0);

    // Reload after a conflict: GET the entry's latest state.
    reply = respond(200, { id: 's1', status: 'planned', lock_version: 9, scheduled_at: '2027-05-06T04:30:00Z', timezone: 'Asia/Kolkata', notes: 'theirs' });
    const latest = await ScheduleService.getPlan('s1');
    assert.equal(new URL(calls[0].url).pathname, '/api/schedules/s1');
    assert.equal(calls[0].init?.method ?? 'GET', 'GET');
    assert.deepEqual([latest.lockVersion, latest.notes], [9, 'theirs']);
  } finally {
    globalThis.fetch = realFetch;
  }
  console.log('reschedule/cancel service: OK (lock_version sent, conflicts surfaced not retried, errors classified, nothing sent when invalid)');
}

/** Step 10: the preferences service the calendar and Add to Calendar use (mocked fetch). */
async function settingsServiceChecks(outDir) {
  const { SettingsService, SettingsApiError, DEFAULT_SETTINGS } = load(path.join(outDir, 'lib/services/settings.service.js'));
  assert.deepEqual([DEFAULT_SETTINGS.calendarDefaultView, DEFAULT_SETTINGS.defaultPlanTime, DEFAULT_SETTINGS.timezone], ['month', '09:00', null]);
  const calls = [];
  let reply = null;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const respond = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body });
  const fails = async (promise) => promise.then(() => assert.fail('expected SettingsApiError'), (e) => {
    assert.ok(e instanceof SettingsApiError, String(e));
    return e;
  });
  try {
    reply = respond(200, { timezone: 'Asia/Kolkata', calendar_default_view: 'week', default_plan_time: '10:30', saved: true, updated_at: '2026-10-11T10:00:00Z' });
    const got = await SettingsService.get();
    assert.equal(new URL(calls[0].url).pathname, '/api/settings/me');
    assert.deepEqual([got.timezone, got.calendarDefaultView, got.defaultPlanTime, got.saved], ['Asia/Kolkata', 'week', '10:30', true]);

    reply = respond(200, { timezone: null, calendar_default_view: 'day', default_plan_time: '08:05', saved: true, updated_at: '2026-10-11T10:01:00Z' });
    const saved = await SettingsService.save({ timezone: '   ', calendarDefaultView: 'day', defaultPlanTime: '08:05' });
    assert.equal(calls[1].init.method, 'PUT');
    // Exactly the three preferences, snake_case; a blank zone is sent as null (= browser zone). Nothing else.
    assert.deepEqual(JSON.parse(calls[1].init.body), { timezone: null, calendar_default_view: 'day', default_plan_time: '08:05' });
    assert.deepEqual([saved.calendarDefaultView, saved.timezone], ['day', null]);

    reply = respond(422, { detail: [{ loc: ['body', 'timezone'], msg: 'Value error, must be a valid IANA time zone', type: 'value_error' }] });
    const invalid = await fails(SettingsService.save({ timezone: 'Mars/Base', calendarDefaultView: 'month', defaultPlanTime: '09:00' }));
    assert.equal(invalid.kind, 'validation');
    assert.match(invalid.message, /IANA/);
    reply = respond(401, { detail: 'Not authenticated' });
    assert.equal((await fails(SettingsService.get())).kind, 'auth');
    reply = respond(500, { detail: 'boom' });
    assert.equal((await fails(SettingsService.save({ timezone: null, calendarDefaultView: 'month', defaultPlanTime: '09:00' }))).kind, 'server');
    reply = new TypeError('Failed to fetch');
    const network = await fails(SettingsService.save({ timezone: null, calendarDefaultView: 'month', defaultPlanTime: '09:00' }));
    assert.ok(network.kind === 'network' && /Nothing was saved/.test(network.message));
  } finally {
    globalThis.fetch = realFetch;
  }
  console.log('settings service: OK (GET/PUT /settings/me, three fields only, blank zone → null, error kinds)');
}

/** Step 11: only a server rejection (401/403) may end the session; outages must not sign the user out. */
async function sessionRuleChecks(outDir) {
  const { errorFromResponse, isSessionRejected } = load(path.join(outDir, 'lib/api-errors.js'));
  const response = (status, body) => ({ ok: false, status, statusText: String(status), json: async () => body });
  assert.equal(isSessionRejected(await errorFromResponse(response(401, { detail: 'Not authenticated' }))), true);
  assert.equal(isSessionRejected(await errorFromResponse(response(403, { detail: 'Could not validate credentials' }))), true);
  for (const status of [404, 422, 500, 502, 503]) {
    assert.equal(isSessionRejected(await errorFromResponse(response(status, { detail: 'x' }))), false, `HTTP ${status} must not end the session`);
  }
  assert.equal(isSessionRejected(new TypeError('Failed to fetch')), false);  // backend unreachable / restarting
  assert.equal(isSessionRejected(new Error('boom')), false);
  assert.equal(isSessionRejected(undefined), false);
  console.log('session rule: OK (only 401/403 end the session; network errors and 5xx keep it)');
}

function rangeChecks(outDir, zone) {
  process.env.TZ = zone;  // Node applies TZ on assignment
  installResolver(outDir);
  const r = load(path.join(outDir, 'lib/calendar-range.js'));
  const midnight = (d) => d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0 && d.getMilliseconds() === 0;
  const hours = (g) => (g.end - g.start) / 3600000;
  for (const anchor of [new Date(2026, 9, 10, 15), new Date(2027, 2, 28, 12), new Date(2027, 9, 31, 12),
                        new Date(2027, 2, 14, 12), new Date(2027, 10, 7, 12), new Date(2026, 11, 31, 23)]) {
    for (const view of ['day', 'week', 'month']) {
      const g = r.calendarRange(view, anchor);
      assert.ok(midnight(g.start) && midnight(g.end), `${zone} ${view}: boundaries at local midnight`);
      assert.ok(g.start <= anchor && anchor < g.end, `${zone} ${view}: [start, end) contains the anchor`);
      if (view !== 'month') {
        assert.equal(r.calendarRange(view, r.shiftAnchor(view, anchor, 1)).start.getTime(), g.end.getTime());
        assert.equal(r.calendarRange(view, r.shiftAnchor(view, anchor, -1)).end.getTime(), g.start.getTime());
      } else {
        assert.equal(g.days.length % 7, 0);
      }
    }
  }
  const day = (y, m, d) => hours(r.calendarRange('day', new Date(y, m, d, 12)));
  const expected = {
    'Europe/London': [[2027, 2, 28, 23], [2027, 9, 31, 25]],
    'America/New_York': [[2027, 2, 14, 23], [2027, 10, 7, 25]],
    'Asia/Kolkata': [[2027, 2, 28, 24], [2027, 9, 31, 24]],
  }[zone] || [];
  for (const [y, m, d, h] of expected) assert.equal(day(y, m, d), h, `${zone} ${y}-${m + 1}-${d} is ${h} h`);
  console.log(`ranges ${zone}: OK`);
}

const zoneArg = process.argv.find((a) => a.startsWith(ZONE_ARG));
if (zoneArg) {
  rangeChecks(process.argv.find((a) => a.startsWith(OUT_ARG)).slice(OUT_ARG.length), zoneArg.slice(ZONE_ARG.length));
} else {
  const outDir = compile();
  try {
    componentChecks(outDir);
    zonedTimeChecks(outDir);
    await planningServiceChecks(outDir);
    cardActionChecks(outDir);
    await rescheduleCancelChecks(outDir);
    await settingsServiceChecks(outDir);
    await sessionRuleChecks(outDir);
    for (const zone of ['Europe/London', 'America/New_York', 'Asia/Kolkata', 'UTC']) {
      const child = spawnSync(process.execPath, [SCRIPT, `${ZONE_ARG}${zone}`, `${OUT_ARG}${outDir}`], { encoding: 'utf8' });
      process.stdout.write(child.stdout);
      if (child.status !== 0) {
        process.stderr.write(child.stderr);
        throw new Error(`range checks failed in ${zone}`);
      }
    }
    console.log('calendar checks passed');
  } finally {
    fs.rmSync(outDir, { recursive: true, force: true });
  }
}
