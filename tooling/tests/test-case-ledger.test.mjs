import assert from 'node:assert/strict'
import test from 'node:test'
import path from 'node:path'
import { validateJunitXml, validateSmokeReport, validateVitestJson } from '../checks/case-ledger.mjs'

const vitest = overrides => {
  const cases = [{ id: 'fixture.test.ts > one assertion', status: 'PASS' }]
  const counts = { PASS: 1, FAIL: 0, SKIP: 0, TODO: 0, XFAIL: 0, XPASS: 0, PENDING: 0, UNKNOWN: 0 }
  return JSON.stringify({ schema: 'ordessa.vitest.case-ledger.v1', total: 1, counts, cases, ...overrides })
}

test('Vitest case ledger accepts a nonempty all-PASS row list', () => assert.equal(validateVitestJson(vitest(), 'fixture').length, 1))
test('Vitest case ledger rejects missing/empty/malformed reports', () => {
  for (const text of ['', '{', JSON.stringify({ schema: 'wrong', total: 1, counts: {}, cases: [] }),
    JSON.stringify({ schema: 'ordessa.vitest.case-ledger.v1', total: 0, counts: {}, cases: [] })]) {
    assert.throws(() => validateVitestJson(text, 'fixture'))
  }
})
test('Vitest case ledger rejects skip, todo, xfail, xpass, pending, failure and unknown', () => {
  for (const status of ['SKIP', 'TODO', 'XFAIL', 'XPASS', 'PENDING', 'FAIL', 'UNKNOWN']) {
    const counts = { PASS: 0, FAIL: 0, SKIP: 0, TODO: 0, XFAIL: 0, XPASS: 0, PENDING: 0, UNKNOWN: 0 }
    counts[status] = 1
    assert.throws(() => validateVitestJson(JSON.stringify({ schema: 'ordessa.vitest.case-ledger.v1', total: 1, counts, cases: [{ id: 'case', status }] }), 'fixture'))
  }
})
test('Vitest case ledger rejects count mismatch and unnamed rows', () => {
  assert.throws(() => validateVitestJson(vitest({ total: 2 }), 'fixture'))
  assert.throws(() => validateVitestJson(JSON.stringify({ schema: 'ordessa.vitest.case-ledger.v1', total: 1, counts: { PASS: 1, FAIL: 0, SKIP: 0, TODO: 0, XFAIL: 0, XPASS: 0, PENDING: 0, UNKNOWN: 0 }, cases: [{ id: '', status: 'PASS' }] }), 'fixture'))
})
test('JUnit accepts exact-count flat and nested suites', () => {
  const flat = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="a"/></testsuite>'
  const nested = '<testsuites tests="2" failures="0" errors="0" skipped="0"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="b"/></testsuite></testsuites>'
  assert.equal(validateJunitXml(flat, 'fixture').length, 1)
  assert.equal(validateJunitXml(nested, 'fixture').length, 2)
})
test('JUnit rejects arbitrary roots and root or suite count mismatch', () => {
  for (const xml of [
    '<report tests="1" failures="0" errors="0" skipped="0"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite></report>',
    '<testsuites tests="2" failures="0" errors="0" skipped="0"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite></testsuites>',
    '<testsuites tests="1" failures="0" errors="0" skipped="0"><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite></testsuites>',
    '<testsuite tests="1"><testcase name="a"/></testsuite>',
  ]) assert.throws(() => validateJunitXml(xml, 'fixture'))
})
test('JUnit rejects empty, malformed, skipped, failed and errored reports', () => {
  for (const xml of ['', '<testsuites tests="0" failures="0" errors="0" skipped="0"><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>', '<testsuite tests="1" failures="0" errors="0" skipped="1"><testcase name="s"><skipped/></testcase></testsuite>',
    '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="f"><failure/></testcase></testsuite>', '<testsuite tests="1" failures="0" errors="1" skipped="0"><testcase name="e"><error/></testcase></testsuite>', '<testsuite>']) {
    assert.throws(() => validateJunitXml(xml, 'fixture'))
  }
})
test('smoke gate requires post-assertion marker and structured payload, not exit zero alone', () => {
  assert.throws(() => validateSmokeReport('electron:test:ui-preview', 0, '{}'))
  assert.throws(() => validateSmokeReport('electron:test:ui-preview', 1, 'UI_PREVIEW_OK {}'))
  assert.deepEqual(validateSmokeReport('electron:test:ui-preview', 0,
    '{"boot":{},"history":{},"inputMenu":{}}\nUI_PREVIEW_OK screenshots=controlled'),
    [{ id: 'controlled UI preview assertions', status: 'PASS' }])
})
test('unsupported smoke adapter fails closed', () => assert.throws(() => validateSmokeReport('unknown', 0, '{}')))



import { validateNodeEventLedger } from '../checks/node-event-ledger.mjs'
const nodeRow = (name, sourceFile, sequence, eventSequence, overrides = {}) => ({
  kind: 'test', name, status: 'PASS', nesting: 0, testNumber: sequence,
  sourceFile, line: sequence, column: 1, sequence, eventSequence, ...overrides,
})
const nodeCounts = (tests, overrides = {}) => ({
  tests, suites: 0, passed: tests, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: tests, ...overrides,
})
const nodeSummary = (executionScope, eventSequence, tests, overrides = {}) => ({
  executionScope, eventSequence, success: true, counts: nodeCounts(tests, overrides),
})
const nodeLedger = (rows, summaries, overrides = {}) => ({
  schema: 'ordessa.node.test.event-ledger.v2', protocolError: null, rows, summaries, ...overrides,
})
const validateNodeFixture = (ledger, expectedExecutionScopes = ledger.summaries.filter(item => item.executionScope !== null).map(item => item.executionScope)) => {
  const normalized = structuredClone(ledger)
  const absolute = value => path.isAbsolute(value) ? value : path.resolve('/fixture', value)
  for (const row of normalized.rows) row.sourceFile = absolute(row.sourceFile)
  for (const summary of normalized.summaries) if (summary.executionScope !== null) summary.executionScope = absolute(summary.executionScope)
  return validateNodeEventLedger(JSON.stringify(normalized), 'fixture', {
    expectedExecutionScopes: expectedExecutionScopes.map(absolute),
  })
}

test('Node event ledger reconciles terminal tests separately from suites', () => {
  const rows = [
    nodeRow('one', 'x.mjs', 1, 1, { nesting: 1 }),
    nodeRow('two', 'x.mjs', 2, 2, { nesting: 1 }),
    nodeRow('child', 'x.mjs', 3, 3, { nesting: 2, testNumber: 1 }),
    { ...nodeRow('suite', 'x.mjs', 4, 4, { nesting: 0, kind: 'suite' }), testNumber: 1 },
  ]
  const ledger = nodeLedger(rows, [nodeSummary('x.mjs', 5, 3, { suites: 1, topLevel: 1 }), nodeSummary(null, 6, 3, { suites: 1, topLevel: 1 })])
  assert.equal(validateNodeFixture(ledger).length, 3)
})
test('Node event ledger rejects non-pass events, summaries, missing and mismatched evidence', () => {
  const base = nodeLedger([nodeRow('x', 'x.mjs', 1, 1)], [nodeSummary('x.mjs', 2, 1), nodeSummary(null, 3, 1)])
  for (const mutate of [
    x => { x.rows[0].status = 'FAIL'; x.summaries[0].success = false; x.summaries[0].counts.failed = 1; x.summaries[0].counts.passed = 0 },
    x => { x.rows[0].status = 'SKIP'; x.summaries[0].counts.skipped = 1; x.summaries[0].counts.passed = 0 },
    x => { x.rows[0].status = 'TODO'; x.summaries[0].counts.todo = 1; x.summaries[0].counts.passed = 0 },
    x => { x.summaries[0].counts.tests = 2 },
    x => { x.summaries[0].counts.suites = 1 },
    x => { x.summaries[0].counts.cancelled = 1 },
    x => { x.summaries[0].counts.topLevel = 2 },
    x => { x.summaries[0].success = false },
    x => { x.protocolError = 'missing summary' },
  ]) {
    const item = structuredClone(base); mutate(item)
    assert.throws(() => validateNodeFixture(item))
  }
})
test('Node event ledger keeps repeated helper-generated tests distinct by event sequence', () => {
  const sameDefinition = { kind: 'test', name: 'generated case', status: 'PASS', nesting: 2, testNumber: 1, sourceFile: 'x.mjs', line: 20, column: 4 }
  const rows = [{ ...sameDefinition, sequence: 1, eventSequence: 1 }, { ...sameDefinition, sequence: 2, eventSequence: 2 }]
  const ledger = nodeLedger(rows, [nodeSummary('x.mjs', 3, 2, { topLevel: 0 }), nodeSummary(null, 4, 2, { topLevel: 0 })])
  assert.equal(validateNodeFixture(ledger).length, 2)
})
test('Node event ledger rejects missing, duplicate, or reordered event sequence', () => {
  const base = nodeLedger([nodeRow('one', 'x.mjs', 1, 1), nodeRow('two', 'x.mjs', 2, 2)], [nodeSummary('x.mjs', 3, 2), nodeSummary(null, 4, 2)])
  for (const sequences of [[1, 1], [2, 1], [1, undefined]]) {
    const ledger = structuredClone(base)
    ledger.rows.forEach((row, index) => { if (sequences[index] === undefined) delete row.sequence; else row.sequence = sequences[index] })
    assert.throws(() => validateNodeFixture(ledger))
  }
  for (const eventSequences of [[1, 1], [2, 1], [1, undefined]]) {
    const ledger = structuredClone(base)
    ledger.rows.forEach((row, index) => { if (eventSequences[index] === undefined) delete row.eventSequence; else row.eventSequence = eventSequences[index] })
    assert.throws(() => validateNodeFixture(ledger))
  }
})
test('Node event ledger requires exactly one cumulative summary', () => {
  const row = nodeRow('one', 'x.mjs', 1, 1)
  const perFile = nodeSummary('x.mjs', 2, 1)
  assert.throws(() => validateNodeFixture(nodeLedger([row], [perFile])))
  assert.throws(() => validateNodeFixture(nodeLedger([row], [perFile, nodeSummary(null, 3, 1), nodeSummary(null, 4, 1)])))
})
test('Node event ledger rejects cumulative summary without explicit file:null', () => {
  const row = nodeRow('one', 'x.mjs', 1, 1)
  const malformed = { success: true, counts: nodeCounts(1), eventSequence: 2 }
  assert.throws(() => validateNodeFixture(nodeLedger([row], [nodeSummary('x.mjs', 2, 1), malformed])))
})
test('Node ledger accepts imported source modules under one execution summary without rewriting either path', () => {
  const sourceFile = '/pkg/tests/node.test.mjs'
  const executionScope = '/pkg/tests'
  const rows = [nodeRow('imported test', sourceFile, 1, 1)]
  const ledger = nodeLedger(rows, [nodeSummary(executionScope, 2, 1), nodeSummary(null, 3, 1)])
  assert.equal(validateNodeFixture(ledger).length, 1)
  assert.equal(ledger.rows[0].sourceFile, sourceFile)
  assert.equal(ledger.summaries[0].executionScope, executionScope)
})
test('Node ledger accepts complete direct-source partitions across multiple execution summaries', () => {
  const rows = [nodeRow('a', 'a.mjs', 1, 1), nodeRow('b', 'b.mjs', 2, 3)]
  const ledger = nodeLedger(rows, [nodeSummary('a.mjs', 2, 1), nodeSummary('b.mjs', 4, 1), nodeSummary(null, 5, 2)])
  assert.equal(validateNodeFixture(ledger).length, 2)
})
test('Node ledger rejects ambiguous imported source attribution across multiple executions', () => {
  const rows = [nodeRow('a', 'shared.mjs', 1, 1), nodeRow('b', 'shared.mjs', 2, 3)]
  const ledger = nodeLedger(rows, [nodeSummary('entry-a.mjs', 2, 1), nodeSummary('entry-b.mjs', 4, 1), nodeSummary(null, 5, 2)])
  assert.throws(() => validateNodeFixture(ledger), /ambiguous/)
})
test('Node ledger requires a per-file summary in addition to the cumulative summary', () => {
  const ledger = nodeLedger([nodeRow('one', 'x.mjs', 1, 1)], [nodeSummary(null, 2, 1)])
  assert.throws(() => validateNodeFixture(ledger, ['x.mjs']), /missing per-file execution summary/)
})
test('Node ledger refuses rows outside a single execution summary sequence boundary', () => {
  const ledger = nodeLedger([nodeRow('one', 'x.mjs', 1, 3)], [nodeSummary('entry', 2, 1), nodeSummary(null, 4, 1)])
  assert.throws(() => validateNodeFixture(ledger), /after its sole execution-scope summary/)
})
test('Node reporter refuses unknown details.type instead of calling it a test', async () => {
  const { mkdtemp, readFile, rm } = await import('node:fs/promises')
  const path = await import('node:path')
  const { fileURLToPath } = await import('node:url')
  const { default: reporter } = await import('../checks/node_test_event_reporter.mjs')
  const candidateRoot = path.dirname(fileURLToPath(import.meta.url))
  const directory = await mkdtemp(path.join(candidateRoot, 'reporter-test-'))
  const destination = path.join(directory, 'ledger.json')
  const prior = process.env.ORDESSA_NODE_TEST_LEDGER
  process.env.ORDESSA_NODE_TEST_LEDGER = destination
  try {
    async function* events() {
      yield { type: 'test:pass', data: { name: 'unknown shape', details: { type: 'other' }, nesting: 0, testNumber: 1, file: 'x.mjs', line: 1, column: 1 } }
      yield { type: 'test:summary', data: { file: null, success: true, counts: { tests: 1, suites: 0, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: 1 } } }
    }
    for await (const _ of reporter(events())) {}
    const ledger = JSON.parse(await readFile(destination, 'utf8'))
    assert.equal(ledger.rows.length, 0)
    assert.match(ledger.protocolError, /unsupported .*details.type/)
    assert.throws(() => validateNodeFixture(ledger))
  } finally {
    if (prior === undefined) delete process.env.ORDESSA_NODE_TEST_LEDGER
    else process.env.ORDESSA_NODE_TEST_LEDGER = prior
    await rm(directory, { recursive: true, force: true })
  }
})
test('Node reporter serializes the Node cumulative undefined scope as explicit file:null', async () => {
  const { mkdtemp, readFile, rm } = await import('node:fs/promises')
  const path = await import('node:path')
  const { fileURLToPath } = await import('node:url')
  const { default: reporter } = await import('../checks/node_test_event_reporter.mjs')
  const candidateRoot = path.dirname(fileURLToPath(import.meta.url))
  const directory = await mkdtemp(path.join(candidateRoot, 'summary-scope-test-'))
  const destination = path.join(directory, 'ledger.json')
  const prior = process.env.ORDESSA_NODE_TEST_LEDGER
  process.env.ORDESSA_NODE_TEST_LEDGER = destination
  try {
    async function* events() {
      yield { type: 'test:pass', data: { name: 'one', details: { type: 'test' }, nesting: 0, testNumber: 1, file: 'definition.mjs', line: 1, column: 1 } }
      yield { type: 'test:summary', data: { file: 'entry-directory', success: true, counts: { tests: 1, suites: 0, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: 1 } } }
      yield { type: 'test:summary', data: { file: undefined, success: true, counts: { tests: 1, suites: 0, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: 1 } } }
    }
    for await (const _ of reporter(events())) {}
    const ledger = JSON.parse(await readFile(destination, 'utf8'))
    assert.equal(ledger.schema, 'ordessa.node.test.event-ledger.v2')
    assert.equal(ledger.rows[0].sourceFile, 'definition.mjs')
    assert.equal(ledger.rows[0].eventSequence, 1)
    assert.equal(ledger.summaries[0].executionScope, 'entry-directory')
    assert.equal(ledger.summaries[0].eventSequence, 2)
    assert.equal(Object.hasOwn(ledger.summaries[1], 'executionScope'), true)
    assert.equal(ledger.summaries[1].executionScope, null)
    assert.equal(ledger.summaries[1].eventSequence, 3)
    assert.equal(validateNodeFixture(ledger).length, 1)
  } finally {
    if (prior === undefined) delete process.env.ORDESSA_NODE_TEST_LEDGER
    else process.env.ORDESSA_NODE_TEST_LEDGER = prior
    await rm(directory, { recursive: true, force: true })
  }
})


test('Node entry scope must match the exact directory argument, not its index module', () => {
  const source = '/workspace/tests/node.test.mjs'
  const ledger = nodeLedger([nodeRow('imported test', source, 1, 1)], [
    nodeSummary('/workspace/tests', 2, 1), nodeSummary(null, 3, 1),
  ])
  assert.equal(validateNodeFixture(ledger, ['/workspace/tests']).length, 1)
  const wrong = structuredClone(ledger)
  wrong.summaries[0].executionScope = '/workspace/tests/index.js'
  assert.throws(() => validateNodeFixture(wrong, ['/workspace/tests']), /do not exactly match/)
})

test('Node entry scope rejects a missing summary for one of multiple expected entries', () => {
  const ledger = nodeLedger([
    nodeRow('one', '/workspace/a.test.mjs', 1, 1),
    nodeRow('two', '/workspace/b.test.mjs', 2, 2),
  ], [nodeSummary('/workspace/a.test.mjs', 3, 2), nodeSummary(null, 4, 2)])
  assert.throws(() => validateNodeFixture(ledger, ['/workspace/a.test.mjs', '/workspace/b.test.mjs']), /do not exactly match/)
})

test('Node entry scope still rejects imported-source ambiguity across multiple entries', () => {
  const rows = [
    nodeRow('a', '/workspace/shared/helper.mjs', 1, 1),
    nodeRow('b', '/workspace/shared/helper.mjs', 2, 3),
  ]
  const ledger = nodeLedger(rows, [
    nodeSummary('/workspace/a.test.mjs', 2, 1),
    nodeSummary('/workspace/b.test.mjs', 4, 1),
    nodeSummary(null, 5, 2),
  ])
  assert.throws(() => validateNodeFixture(ledger, ['/workspace/a.test.mjs', '/workspace/b.test.mjs']), /ambiguous/)
})

test('Node expected entries reject an empty or duplicate caller list', () => {
  const ledger = nodeLedger([nodeRow('one', '/workspace/one.test.mjs', 1, 1)], [
    nodeSummary('/workspace/one.test.mjs', 2, 1), nodeSummary(null, 3, 1),
  ])
  assert.throws(() => validateNodeFixture(ledger, []), /nonempty absolute expected Node entry list/)
  assert.throws(() => validateNodeFixture(ledger, ['/workspace/one.test.mjs', '/workspace/one.test.mjs']), /contains duplicates/)
})
