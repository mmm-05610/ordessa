import path from 'node:path'

const fail = message => { throw new Error(message) }
const COUNT_KEYS = ['tests', 'suites', 'passed', 'failed', 'cancelled', 'skipped', 'todo', 'topLevel']

function validateCounts(summary, rows, suiteName) {
  if (summary.success !== true || !summary.counts || typeof summary.counts !== 'object') fail(`${suiteName}: missing or unsuccessful Node test:summary`)
  const counts = summary.counts
  for (const key of COUNT_KEYS) if (!Number.isInteger(counts[key]) || counts[key] < 0) fail(`${suiteName}: missing/invalid summary count ${key}`)
  const tests = rows.filter(row => row.kind === 'test')
  const suites = rows.filter(row => row.kind === 'suite')
  if (counts.tests !== tests.length) fail(`${suiteName}: summary tests=${counts.tests}, event test rows=${tests.length}`)
  if (counts.suites !== suites.length) fail(`${suiteName}: summary suites=${counts.suites}, event suite rows=${suites.length}`)
  if (counts.topLevel !== rows.filter(row => row.nesting === 0).length) fail(`${suiteName}: summary topLevel does not match event rows`)
  const actual = {
    passed: tests.filter(row => row.status === 'PASS').length,
    failed: tests.filter(row => row.status === 'FAIL').length,
    skipped: tests.filter(row => row.status === 'SKIP').length,
    todo: tests.filter(row => row.status === 'TODO').length,
  }
  for (const key of Object.keys(actual)) if (counts[key] !== actual[key]) fail(`${suiteName}: summary ${key}=${counts[key]}, event rows=${actual[key]}`)
  if (counts.cancelled !== 0 || counts.failed !== 0 || counts.skipped !== 0 || counts.todo !== 0) fail(`${suiteName}: Node summary includes non-PASS outcomes`)
  if (counts.passed !== counts.tests || tests.some(row => row.status !== 'PASS')) fail(`${suiteName}: Node test suite is not all-PASS`)
}

export function validateNodeEventLedger(text, suiteName, { expectedExecutionScopes } = {}) {
  if (!Array.isArray(expectedExecutionScopes) || expectedExecutionScopes.length === 0 || expectedExecutionScopes.some(scope => typeof scope !== 'string' || !scope || !pathIsAbsolute(scope))) {
    fail(`${suiteName}: caller must provide a nonempty absolute expected Node entry list`)
  }
  if (new Set(expectedExecutionScopes).size !== expectedExecutionScopes.length) fail(`${suiteName}: caller expected Node entry list contains duplicates`)
  let ledger
  try { ledger = JSON.parse(text) } catch (error) { fail(`${suiteName}: malformed Node event ledger: ${error.message}`) }
  if (!ledger || ledger.schema !== 'ordessa.node.test.event-ledger.v2' || !Array.isArray(ledger.rows) || !ledger.rows.length || !Array.isArray(ledger.summaries) || !ledger.summaries.length) {
    fail(`${suiteName}: missing, unsupported, or empty Node event ledger`)
  }
  const rows = ledger.rows
  const eventSequences = new Set()
  for (const row of rows) {
    if (!row || !['test', 'suite'].includes(row.kind) || typeof row.name !== 'string' || !row.name || !['PASS', 'FAIL', 'SKIP', 'TODO', 'UNKNOWN'].includes(row.status) || !Number.isInteger(row.nesting) || row.nesting < 0) fail(`${suiteName}: malformed Node test event row`)
    if (!Number.isInteger(row.testNumber) || row.testNumber < 1 || !Number.isInteger(row.sequence) || row.sequence < 1 || !Number.isInteger(row.eventSequence) || row.eventSequence < 1 || typeof row.sourceFile !== 'string' || !row.sourceFile || !Number.isInteger(row.line) || row.line < 1 || !Number.isInteger(row.column) || row.column < 1) fail(`${suiteName}: missing Node event identity/location`)
    if (row.status !== 'PASS') fail(`${suiteName}: non-PASS Node event ${row.status}: ${row.name}`)
    if (eventSequences.has(row.eventSequence)) fail(`${suiteName}: duplicate Node event sequence ${row.eventSequence}`)
    eventSequences.add(row.eventSequence)
  }
  if (rows.some((row, index) => row.sequence !== index + 1) || rows.some((row, index) => index > 0 && row.eventSequence <= rows[index - 1].eventSequence)) fail(`${suiteName}: Node event sequence is missing, repeated, or out of order`)

  const summaries = ledger.summaries
  const summaryScopes = new Set()
  for (const summary of summaries) {
    if (!summary || !Object.hasOwn(summary, 'executionScope') || !(summary.executionScope === null || (typeof summary.executionScope === 'string' && summary.executionScope.length > 0))) fail(`${suiteName}: summary must have an explicit execution scope`)
    if (!Number.isInteger(summary.eventSequence) || summary.eventSequence < 1) fail(`${suiteName}: summary lacks event sequence attribution`)
    if (summaryScopes.has(summary.executionScope)) fail(`${suiteName}: duplicate Node summary scope ${summary.executionScope ?? '<cumulative>'}`)
    summaryScopes.add(summary.executionScope)
  }
  if (summaries.some((summary, index) => index > 0 && summary.eventSequence <= summaries[index - 1].eventSequence)) fail(`${suiteName}: Node summary event sequence is missing or reordered`)
  const cumulative = summaries.filter(item => item && item.executionScope === null)
  if (cumulative.length !== 1 || summaries.at(-1) !== cumulative[0]) fail(`${suiteName}: missing, ambiguous, or non-final cumulative Node test:summary`)
  const finalSummary = cumulative[0]
  if (finalSummary.eventSequence <= rows.at(-1).eventSequence) fail(`${suiteName}: cumulative summary precedes terminal test events`)

  const perFile = summaries.filter(item => item.executionScope !== null)
  if (perFile.length === 0) fail(`${suiteName}: missing per-file execution summary`)
  const actualScopes = perFile.map(summary => summary.executionScope)
  const expectedScopes = new Set(expectedExecutionScopes)
  if (actualScopes.length !== expectedExecutionScopes.length || actualScopes.some(scope => !expectedScopes.has(scope))) {
    fail(`${suiteName}: per-entry summaries do not exactly match the caller's Node entry list; expected=${JSON.stringify(expectedExecutionScopes)}, actual=${JSON.stringify(actualScopes)}`)
  }
  let covered = []
  if (perFile.length === 1) {
    // A single per-file summary scopes the full child entry. Its test rows may
    // have sourceFile values from imported sibling modules; keep that provenance.
    const summary = perFile[0]
    if (rows.some(row => row.eventSequence >= summary.eventSequence)) fail(`${suiteName}: terminal event occurs after its sole execution-scope summary`)
    validateCounts(summary, rows, suiteName)
    covered = rows
  } else {
    // With multiple process-isolated files, Node's public event payload does not
    // expose a worker/entry id on terminal rows. Only accept direct source-file
    // attribution; imported definitions across workers remain explicitly unsupported.
    const claimed = new Set()
    for (const summary of perFile) {
      const scopedRows = rows.filter(row => row.sourceFile === summary.executionScope)
      if (!scopedRows.length) fail(`${suiteName}: execution summary has no direct-source terminal rows; multi-file import attribution is ambiguous`)
      if (scopedRows.some(row => row.eventSequence >= summary.eventSequence)) fail(`${suiteName}: terminal row is after its execution summary`)
      for (const row of scopedRows) {
        if (claimed.has(row.sequence)) fail(`${suiteName}: terminal row attributed to more than one execution summary`)
        claimed.add(row.sequence)
      }
      validateCounts(summary, scopedRows, suiteName)
    }
    if (claimed.size !== rows.length) fail(`${suiteName}: unassigned terminal rows; multi-file source/execution attribution is ambiguous`)
    covered = rows
  }
  validateCounts(finalSummary, covered, suiteName)
  if (ledger.protocolError) fail(`${suiteName}: reporter observed malformed or incomplete Node events: ${ledger.protocolError}`)
  return rows.filter(row => row.kind === 'test').map(row => ({ id: `${row.sourceFile}:${row.line}:${row.column} :: ${row.name} [event ${row.sequence}; ${row.kind} #${row.testNumber}]`, status: 'PASS' }))
}

function pathIsAbsolute(value) {
  return path.isAbsolute(value)
}
