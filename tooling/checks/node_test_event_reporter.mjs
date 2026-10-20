import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

function statusFor(event, data) {
  if (event === 'test:fail') return 'FAIL'
  if (data.skip !== undefined) return 'SKIP'
  if (data.todo !== undefined) return 'TODO'
  if (event !== 'test:pass') return 'UNKNOWN'
  return 'PASS'
}
export default async function * nodeTestEventReporter(source) {
  const rows = []
  const summaries = []
  let protocolError = null
  let eventSequenceCounter = 0
  for await (const event of source) {
    if (['test:diagnostic', 'test:stderr', 'test:stdout'].includes(event.type)) {
      const message = event.data?.message
      if (typeof message === 'string' && message) yield `${message}${message.endsWith('\n') ? '' : '\n'}`
    } else if (event.type === 'test:pass' || event.type === 'test:fail') {
      const eventSequence = ++eventSequenceCounter
      const data = event.data
      const details = data?.details
      if (!details || !['test', 'suite'].includes(details.type)) {
        protocolError ??= `unsupported ${event.type} details.type: ${String(details?.type)}`
        continue
      }
      const kind = details.type
      if (!data || typeof data.name !== 'string' || !data.name || !Number.isInteger(data.nesting) || !Number.isInteger(data.testNumber) || typeof data.file !== 'string' || !data.file || !Number.isInteger(data.line) || !Number.isInteger(data.column)) {
        protocolError ??= `invalid ${event.type} payload`
        continue
      }
      rows.push({
        sequence: rows.length + 1, eventSequence, kind, name: data.name, status: statusFor(event.type, data), nesting: data.nesting,
        testNumber: data.testNumber, sourceFile: data.file, line: data.line, column: data.column,
      })
    } else if (event.type === 'test:summary') {
      const eventSequenceForSummary = ++eventSequenceCounter
      const data = event.data
      const counts = data?.counts
      const file = data?.file === undefined || data?.file === null ? null : data.file
      if (!data || !(file === null || (typeof file === 'string' && file.length > 0)) || typeof data.success !== 'boolean' || !counts || typeof counts !== 'object') {
        protocolError ??= 'invalid test:summary payload or file scope'
        continue
      }
      summaries.push({ eventSequence: eventSequenceForSummary, executionScope: file, success: data.success, counts: {
        tests: counts.tests, suites: counts.suites, passed: counts.passed, failed: counts.failed,
        cancelled: counts.cancelled, skipped: counts.skipped, todo: counts.todo, topLevel: counts.topLevel,
      } })
    } else if (event.type === 'test:complete') {
      const data = event.data
      if (!data?.details || typeof data.details.passed !== 'boolean') protocolError ??= 'invalid test:complete payload'
      else if (!data.details.passed) protocolError ??= `test:complete reports failure: ${data.name ?? '<unnamed>'}`
    }
  }
  const destination = process.env.ORDESSA_NODE_TEST_LEDGER
  if (!destination) throw new Error('ORDESSA_NODE_TEST_LEDGER is required')
  const ledger = { schema: 'ordessa.node.test.event-ledger.v2', rows, summaries, protocolError }
  await mkdir(path.dirname(destination), { recursive: true })
  await writeFile(destination, `${JSON.stringify(ledger)}\n`, 'utf8')
  yield `ORDESSA_NODE_EVENT_LEDGER ${destination}\n`
}
