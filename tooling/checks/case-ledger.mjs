import { readFile } from 'node:fs/promises'
import { SaxesParser } from 'saxes'

const fail = message => { throw new Error(message) }

export function validateVitestJson(text, suiteName) {
  let report
  try { report = JSON.parse(text) } catch (error) { fail(`${suiteName}: invalid/missing case-ledger JSON: ${error.message}`) }
  if (!report || report.schema !== 'ordessa.vitest.case-ledger.v1' || !Array.isArray(report.cases) || !report.cases.length) {
    fail(`${suiteName}: missing, malformed, unsupported, or empty case-ledger JSON`)
  }
  const counts = { PASS: 0, FAIL: 0, SKIP: 0, TODO: 0, XFAIL: 0, XPASS: 0, PENDING: 0, UNKNOWN: 0 }
  for (const item of report.cases) {
    if (!item || typeof item.id !== 'string' || !item.id || !(item.status in counts)) fail(`${suiteName}: malformed/unknown case row`)
    counts[item.status]++
  }
  if (report.total !== report.cases.length || !report.counts || Object.keys(counts).some(key => report.counts[key] !== counts[key])) {
    fail(`${suiteName}: case-ledger counts do not reconcile with listed rows`)
  }
  for (const status of Object.keys(counts)) {
    if (status !== 'PASS' && counts[status] !== 0) fail(`${suiteName}: non-pass case status ${status}=${counts[status]}`)
  }
  if (counts.PASS !== report.total || report.total === 0) fail(`${suiteName}: no complete passing cases`)
  return report.cases.map(item => ({ id: item.id, status: 'PASS' }))
}

export function validateJunitXml(text, suiteName) {
  const cases = [], suites = [], elements = [], suiteStack = []
  let documentRoot = null, rootNode = null, rootClosed = false, currentCase = null
  const parser = new SaxesParser({ xmlns: false, fragment: false })
  parser.on('opentag', node => {
    const parent = elements.at(-1) ?? null
    if (!parent) {
      if (documentRoot !== null || rootClosed) fail(`${suiteName}: multiple JUnit document roots`)
      if (node.name !== 'testsuite' && node.name !== 'testsuites') fail(`${suiteName}: unsupported JUnit root ${node.name}`)
      documentRoot = node.name
      rootNode = node
      if (node.name === 'testsuite') { const suite = { node, cases: [] }; suites.push(suite); suiteStack.push(suite) }
    } else if (node.name === 'testsuite') {
      if (parent.name !== 'testsuites' && parent.name !== 'testsuite') fail(`${suiteName}: testsuite outside JUnit suite tree`)
      const suite = { node, cases: [] }; suites.push(suite); suiteStack.push(suite)
    } else if (node.name === 'testcase') {
      if (parent.name !== 'testsuite') fail(`${suiteName}: testcase outside testsuite`)
      if (currentCase) fail(`${suiteName}: nested JUnit testcase`)
      currentCase = { name: node.attributes.name, classname: node.attributes.classname ?? '', status: 'PASS', suitePath: [...suiteStack] }
    } else if (['failure', 'error', 'skipped'].includes(node.name)) {
      if (!currentCase) fail(`${suiteName}: ${node.name} outside testcase`)
      currentCase.status = node.name.toUpperCase()
    } else if (parent.name === 'testsuite' || parent.name === 'testsuites') fail(`${suiteName}: unsupported element ${node.name} in JUnit suite tree`)
    elements.push(node)
  })
  parser.on('closetag', tag => {
    const node = elements.pop()
    if (!node || node.name !== tag.name) fail(`${suiteName}: malformed JUnit element nesting`)
    if (tag.name === 'testcase') {
      if (!currentCase || typeof currentCase.name !== 'string' || !currentCase.name) fail(`${suiteName}: unnamed JUnit testcase`)
      const row = { id: `${currentCase.classname} :: ${currentCase.name}`, status: currentCase.status }
      cases.push(row); for (const suite of currentCase.suitePath) suite.cases.push(row); currentCase = null
    }
    if (tag.name === 'testsuite') suiteStack.pop()
    if (tag.name === documentRoot) rootClosed = true
  })
  parser.write(text).close()
  if (!documentRoot || !rootClosed || elements.length || !cases.length) fail(`${suiteName}: malformed or empty JUnit document`)
  const totals = rows => ({ tests: rows.length, failures: rows.filter(x => x.status === 'FAILURE').length,
    errors: rows.filter(x => x.status === 'ERROR').length, skipped: rows.filter(x => x.status === 'SKIPPED').length })
  const checkCounts = (attrs, rows, label) => {
    const actual = totals(rows)
    for (const key of ['tests', 'failures', 'errors', 'skipped']) {
      if (attrs[key] === undefined || !/^\d+$/.test(String(attrs[key])) || Number(attrs[key]) !== actual[key])
        fail(`${suiteName}: ${label} declared ${key}=${attrs[key] ?? '<missing>'}, parsed ${actual[key]}`)
    }
  }
  if (!rootNode) fail(`${suiteName}: missing root suite counts`)
  if (documentRoot === 'testsuite') checkCounts(rootNode.attributes, cases, 'JUnit root')
  else {
    for (const [i, suite] of suites.entries()) checkCounts(suite.node.attributes, suite.cases, `JUnit testsuite[${i}]`)
    checkCounts(rootNode.attributes, cases, 'JUnit root')
  }
  const nonPass = cases.filter(item => item.status !== 'PASS')
  if (nonPass.length) fail(`${suiteName}: JUnit failure/skip/error rows: ${JSON.stringify(nonPass)}`)
  return cases
}

function jsonValues(output) {
  const values = []
  let start = 0
  while (start < output.length) {
    const objectStart = output.indexOf('{', start)
    if (objectStart < 0) break
    let depth = 0, quoted = false, escaped = false, completed = false
    for (let end = objectStart; end < output.length; end++) {
      const c = output[end]
      if (quoted) {
        if (escaped) escaped = false
        else if (c === '\\') escaped = true
        else if (c === '\"') quoted = false
        continue
      }
      if (c === '\"') quoted = true
      else if (c === '{') depth++
      else if (c === '}' && --depth === 0) {
        try { values.push(JSON.parse(output.slice(objectStart, end + 1))) } catch { /* ordinary log braces */ }
        start = end + 1
        completed = true
        break
      }
    }
    if (!completed) start = objectStart + 1
  }
  return values
}

export function validateSmokeReport(suiteName, exitCode, stdout, stderr = '') {
  if (exitCode !== 0) fail(`${suiteName}: smoke process exited ${exitCode}`)
  const allOutput = `${stdout}\n${stderr}`
  const payload = jsonValues(stdout).at(-1)
  if (!payload || typeof payload !== 'object') fail(`${suiteName}: missing structured smoke summary`)
  let cases
  if (suiteName === 'electron:test:electron') {
    if (payload.ready !== true || payload.nodeAbsent !== true || !Array.isArray(payload.pages) || !Array.isArray(payload.errors) || payload.errors.length) fail(`${suiteName}: incomplete smoke summary`)
    cases = [{ id: 'empty host smoke', status: 'PASS' }]
  } else if (suiteName === 'electron:test:agent-ui') {
    if (!payload.agent || Object.keys(payload.agent).length !== 9 || Object.values(payload.agent).some(value => value !== true) || !Array.isArray(payload.errors) || payload.errors.length) fail(`${suiteName}: incomplete agent UI result`)
    cases = Object.entries(payload.agent).map(([name]) => ({ id: `agent UI: ${name}`, status: 'PASS' }))
  } else if (suiteName === 'electron:test:agent-shell') {
    if (!payload.noHandoff || !payload.authenticatedHello || !Array.isArray(payload.calls) || payload.calls.length !== 2 || payload.nodeAbsent !== true) fail(`${suiteName}: incomplete agent shell result`)
    cases = [{ id: 'absent Server fails closed', status: 'PASS' }, { id: 'authenticated loopback hello only', status: 'PASS' }]
  } else if (suiteName === 'electron:test:extensions' || suiteName === 'electron:test:ui-service') {
    if (!Array.isArray(payload.cases) || payload.cases.length === 0 || payload.hostUnchanged !== true) fail(`${suiteName}: missing scenario report rows`)
    cases = payload.cases.map((item, index) => {
      if (!item || typeof item.name !== 'string' || !item.name) fail(`${suiteName}: unnamed scenario row ${index}`)
      return { id: item.name, status: 'PASS' }
    })
  } else if (suiteName === 'electron:test:ui-foundations') {
    if (payload.hostUnchanged !== true || !payload.geometry?.['360'] || !payload.geometry?.['768'] || !payload.screenshots) fail(`${suiteName}: missing viewport result rows`)
    cases = [{ id: '360px layout/interaction assertions', status: 'PASS' }, { id: '768px layout/interaction assertions', status: 'PASS' }]
  } else if (suiteName === 'electron:test:ui-preview') {
    if (!allOutput.includes('UI_PREVIEW_OK ') || !payload.boot || !payload.history || !payload.inputMenu) fail(`${suiteName}: missing post-assertion completion marker or structured result`)
    cases = [{ id: 'controlled UI preview assertions', status: 'PASS' }]
  } else fail(`${suiteName}: no reviewed smoke report adapter`)
  if (!cases.length) fail(`${suiteName}: smoke report has zero cases`)
  return cases
}

export async function readAndValidateReport({ kind, path, suiteName, expectedExecutionScopes }) {
  let text
  try { text = await readFile(path, 'utf8') } catch (error) { fail(`${suiteName}: missing report file: ${error.message}`) }
  if (!text.trim()) fail(`${suiteName}: empty report file`)
  if (kind === 'vitest-json') return validateVitestJson(text, suiteName)
  if (kind === 'node-junit') return validateJunitXml(text, suiteName)
  if (kind === 'node-event-ledger') return (await import('./node-event-ledger.mjs')).validateNodeEventLedger(text, suiteName, { expectedExecutionScopes })
  fail(`${suiteName}: unsupported reporter ${kind}`)
}
