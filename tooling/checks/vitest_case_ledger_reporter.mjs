import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const STATUS = new Set(['PASS', 'FAIL', 'SKIP', 'TODO', 'XFAIL', 'XPASS', 'PENDING', 'UNKNOWN'])
function classify(task) {
  if (task.fails === true) return task.result?.state === 'pass' ? 'XFAIL' : task.result?.state === 'fail' ? 'XPASS' : 'UNKNOWN'
  if (task.mode === 'skip' || task.result?.state === 'skip' || task.result?.state === 'skipped') return 'SKIP'
  if (task.mode === 'todo') return 'TODO'
  if (task.result?.state === 'fail' || task.result?.state === 'failed') return 'FAIL'
  if (task.result?.state === 'run' || task.result?.state === 'queued' || !task.result?.state) return 'PENDING'
  if (task.result?.state === 'pass' || task.result?.state === 'passed') return 'PASS'
  return 'UNKNOWN'
}
function walk(task, parent, rows) {
  const name = [parent, task.name].filter(Boolean).join(' > ')
  if (task.type === 'suite') {
    for (const child of task.tasks ?? []) walk(child, name, rows)
    if (task.result?.state === 'fail' && !(task.tasks ?? []).length) rows.push({ id: name, status: 'FAIL' })
    return
  }
  if (task.type !== 'test') { rows.push({ id: name, status: 'UNKNOWN' }); return }
  rows.push({ id: name, status: classify(task) })
}
export default class VitestCaseLedgerReporter {
  async onTestRunEnd(testModules) {
    const destination = process.env.ORDESSA_VITEST_CASE_LEDGER
    if (!destination) throw new Error('ORDESSA_VITEST_CASE_LEDGER is required')
    const cases = []
    for (const module of testModules) {
      const task = module.task
      if (task.type !== 'suite') { cases.push({ id: task.name || '<unnamed module>', status: 'UNKNOWN' }); continue }
      const before = cases.length
      walk(task, task.file?.filepath || task.name, cases)
      if (task.result?.state === 'fail' && cases.length === before) cases.push({ id: task.file?.filepath || task.name, status: 'FAIL' })
    }
    const counts = Object.fromEntries([...STATUS].map(status => [status, cases.filter(row => row.status === status).length]))
    const report = { schema: 'ordessa.vitest.case-ledger.v1', total: cases.length, counts, cases }
    await mkdir(path.dirname(destination), { recursive: true })
    await writeFile(destination, `${JSON.stringify(report)}\n`, 'utf8')
  }
}
