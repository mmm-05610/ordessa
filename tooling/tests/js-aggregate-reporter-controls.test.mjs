import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { access, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { readAndValidateReport, validateVitestJson } from '../checks/case-ledger.mjs'
import { validateNodeEventLedger } from '../checks/node-event-ledger.mjs'
import { resolveNodeExecutionScopes } from '../checks/node-execution-scopes.mjs'
import { prepareReportedSuite } from '../checks/reported-suite-runner.mjs'

const repoRoot = path.resolve(process.env.ORDESSA_REPO_ROOT ?? path.resolve(import.meta.dirname, '../..'))
const nodeReporter = path.join(repoRoot, 'tooling/checks/node_test_event_reporter.mjs')
const vitestReporter = path.join(repoRoot, 'tooling/checks/vitest_case_ledger_reporter.mjs')
const mixedShell = path.join(repoRoot, 'tooling/checks/mixed-workspace-lifecycle-shell.sh')
const harnessShell = path.join(repoRoot, 'tooling/checks/npm-harness-packaging-reporter-shell.sh')
const harnessScript = 'mkdir -p .nightly-cache/harness-test-tmp && TMPDIR="${TMPDIR:-$PWD/.nightly-cache/harness-test-tmp}" node --test --test-concurrency=1 "plugins/harness/*/tests/packaging/**/*.test.mjs"'

async function temporaryRoot(t, prefix) {
  const cache = path.join(repoRoot, '.nightly-cache/js-aggregate-caller/control-runs')
  await mkdir(cache, { recursive: true })
  const root = await mkdtemp(path.join(cache, prefix))
  t.after(() => rm(root, { recursive: true, force: true }))
  return root
}

function controlledEnv(root, extra = {}) {
  const home = path.join(root, 'owned-home')
  const userConfig = path.join(root, 'owned-npmrc')
  const globalConfig = path.join(root, 'owned-global-npmrc')
  return {
    PATH: process.env.PATH,
    HOME: home,
    TMPDIR: path.join(root, 'owned-tmp'),
    NODE_OPTIONS: '',
    npm_config_cache: path.join(root, 'owned-npm-cache'),
    npm_config_userconfig: userConfig,
    npm_config_globalconfig: globalConfig,
    npm_config_audit: 'false',
    npm_config_fund: 'false',
    npm_config_update_notifier: 'false',
    ...extra,
  }
}

async function runNpm(root, args, env) {
  return await new Promise((resolve, reject) => {
    const child = spawn('npm', args, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = '', stderr = ''
    child.stdout.on('data', chunk => { stdout += chunk.toString('utf8') })
    child.stderr.on('data', chunk => { stderr += chunk.toString('utf8') })
    child.once('error', reject)
    child.once('close', code => resolve({ code: code ?? 1, stdout, stderr }))
  })
}

async function createMixedWorkspace(root, vitestCase, nodeCase) {
  const workspace = path.join(root, 'packages/mixed-workbench')
  await mkdir(path.join(workspace, 'tests/vitest'), { recursive: true })
  await mkdir(path.join(workspace, 'tests/node'), { recursive: true })
  await writeFile(path.join(root, 'package.json'), JSON.stringify({ private: true, workspaces: ['packages/*'] }))
  await writeFile(path.join(workspace, 'package.json'), JSON.stringify({
    name: 'controlled-mixed-workbench', private: true, type: 'module',
    scripts: {
      pretest: "node -e \"require('node:fs').writeFileSync('pre.marker','pre')\"",
      test: 'vitest run --maxWorkers=1 && node --test tests/',
      posttest: "node -e \"require('node:fs').writeFileSync('post.marker','post')\"",
    },
  }))
  await writeFile(path.join(workspace, 'tests/index.js'), await readFile(path.join(repoRoot, 'packages/interfaces/channels/workbench/shell/workbench/tests/index.js'), 'utf8'))
  await writeFile(path.join(workspace, 'vitest.config.mjs'), "export default { test: { include: ['tests/vitest/**/*.test.jsx'] } }\n")
  await writeFile(path.join(workspace, 'tests/vitest/control.test.jsx'), `import { test, expect } from 'vitest'\n${vitestCase}\n`)
  await writeFile(path.join(workspace, 'tests/control.node.test.mjs'), `import assert from 'node:assert/strict'\nimport test from 'node:test'\n${nodeCase}\n`)
  return workspace
}

test('missing, empty, skip, and wrong-cardinality reports fail closed', async t => {
  const root = await temporaryRoot(t, 'ordessa-js-ledger-controls-')
  const absent = path.join(root, 'absent.json')
  await assert.rejects(readAndValidateReport({ kind: 'vitest-json', path: absent, suiteName: 'absent' }), /missing report file/)
  const empty = path.join(root, 'empty.json')
  await writeFile(empty, ' \n')
  await assert.rejects(readAndValidateReport({ kind: 'vitest-json', path: empty, suiteName: 'empty' }), /empty report file/)
  const skipped = { schema: 'ordessa.vitest.case-ledger.v1', total: 1,
    counts: { PASS: 0, FAIL: 0, SKIP: 1, TODO: 0, XFAIL: 0, XPASS: 0, PENDING: 0, UNKNOWN: 0 },
    cases: [{ id: 'skipped', status: 'SKIP' }] }
  assert.throws(() => validateVitestJson(JSON.stringify(skipped), 'skip'), /non-pass case status SKIP/)
  for (const status of ['XFAIL', 'XPASS', 'TODO']) {
    const rejected = { ...skipped, counts: { ...skipped.counts, PASS: 0, SKIP: 0, [status]: 1 }, cases: [{ id: status, status }] }
    assert.throws(() => validateVitestJson(JSON.stringify(rejected), status), /non-pass case status/)
  }
  const one = path.join(root, 'one.mjs'), extra = path.join(root, 'extra.mjs')
  const ledger = { schema: 'ordessa.node.test.event-ledger.v2', protocolError: null,
    rows: [{ sequence: 1, eventSequence: 1, kind: 'test', name: 'ok', status: 'PASS', nesting: 0,
      testNumber: 1, sourceFile: one, line: 1, column: 1 }],
    summaries: [
      { eventSequence: 2, executionScope: one, success: true, counts: { tests: 1, suites: 0, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: 1 } },
      { eventSequence: 3, executionScope: null, success: true, counts: { tests: 1, suites: 0, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, topLevel: 1 } },
    ] }
  assert.throws(() => validateNodeEventLedger(JSON.stringify(ledger), 'wrong-cardinality', {
    expectedExecutionScopes: [one, extra],
  }), /do not exactly match/)
})

test('all 53 aggregate entries have an explicit report plan without launching suites', async t => {
  const root = await temporaryRoot(t, 'ordessa-js-plan-controls-')
  const inventory = JSON.parse(await readFile(path.join(import.meta.dirname, '../checks/aggregate-suite-inventory.json'), 'utf8'))
  assert.equal(inventory.count, 53)
  assert.equal(inventory.suites.length, inventory.count)
  const seen = new Set()
  for (const [index, suite] of inventory.suites.entries()) {
    assert.ok(!seen.has(suite.name), `duplicate suite ${suite.name}`)
    seen.add(suite.name)
    const plan = await prepareReportedSuite({
      suite,
      rootDir: repoRoot,
      suiteDir: path.join(root, `${String(index + 1).padStart(2, '0')}-${suite.name.replace(/[^A-Za-z0-9._-]+/g, '_')}`),
    })
    if (['typecheck', 'build:examples', 'build:foundations', 'build:app'].includes(suite.name)) {
      assert.equal(plan.kind, 'prerequisite')
      assert.deepEqual(plan.reportFiles, [])
      continue
    }
    if (suite.name.startsWith('electron:')) {
      assert.equal(plan.kind, 'smoke')
      assert.deepEqual(plan.reportFiles, [])
      assert.ok(plan.actualInnerCommand?.[0] === 'node')
      continue
    }
    assert.equal(plan.kind, 'cases', suite.name)
    if (suite.name === 'workspace:packages/interfaces/channels/workbench/shell/workbench') {
      assert.deepEqual(plan.reportFiles.map(item => item.kind), ['vitest-json', 'node-event-ledger'])
      assert.deepEqual(plan.reportFiles[1].expectedExecutionScopes, plan.expectedNodeExecution.scopes)
      assert.ok(plan.actualStages[0].command.some(arg => arg.includes('vitest_case_ledger_reporter.mjs')))
      assert.ok(plan.actualStages[1].command.some(arg => arg.includes('node_test_event_reporter.mjs')))
      continue
    }
    assert.equal(plan.reportFiles.length, 1, suite.name)
    const attachment = plan.reportFiles[0]
    if (attachment.kind === 'node-event-ledger') {
      assert.ok(attachment.expectedExecutionScopes?.length, `${suite.name} lacks prelaunch Node scopes`)
      assert.deepEqual(attachment.expectedExecutionScopes, plan.expectedNodeExecution.scopes)
      const actual = plan.actualInnerCommand ?? plan.command
      assert.ok(actual.some(arg => arg.includes('node_test_event_reporter.mjs')), `${suite.name} lacks Node reporter`)
    } else {
      assert.equal(attachment.kind, 'vitest-json')
      const actual = plan.actualInnerCommand ?? plan.command
      assert.ok(actual.some(arg => arg.includes('vitest_case_ledger_reporter.mjs')), `${suite.name} lacks Vitest reporter`)
    }
  }
  assert.equal(seen.size, 53)
})

test('mixed npm suite preserves pre/post hooks; Vitest failure short-circuits Node; Node skip is rejected', async t => {
  const root = await temporaryRoot(t, 'ordessa-js-mixed-controls-')
  const workspace = await createMixedWorkspace(root,
    "test('vitest passes', () => expect(1).toBe(1))",
    "test('node passes', () => assert.equal(1, 1))")
  const expectedScopes = await resolveNodeExecutionScopes(['tests/'], workspace)
  const runScenario = async scenario => {
    const reports = path.join(root, scenario)
    await mkdir(reports, { recursive: true })
    const vitestFile = path.join(reports, 'vitest.json'), nodeFile = path.join(reports, 'node.json')
    const vitestSource = scenario === 'vitest-fail'
      ? "test('vitest fails', () => expect(1).toBe(2))"
      : "test('vitest passes', () => expect(1).toBe(1))"
    const nodeSource = scenario === 'node-skip'
      ? "test.skip('node skip remains non-pass', () => assert.equal(1, 1))"
      : "test('node passes', () => assert.equal(1, 1))"
    await writeFile(path.join(workspace, 'tests/vitest/control.test.jsx'), `import { test, expect } from 'vitest'\n${vitestSource}\n`)
    await writeFile(path.join(workspace, 'tests/control.node.test.mjs'), `import assert from 'node:assert/strict'\nimport test from 'node:test'\n${nodeSource}\n`)
    await Promise.all([rm(vitestFile, { force: true }), rm(nodeFile, { force: true }),
      rm(path.join(workspace, 'pre.marker'), { force: true }), rm(path.join(workspace, 'post.marker'), { force: true })])
    const env = controlledEnv(root, {
      npm_config_script_shell: mixedShell,
      ORDESSA_MIXED_SCRIPT: 'vitest run --maxWorkers=1 && node --test tests/',
      ORDESSA_VITEST_BIN: path.join(repoRoot, 'node_modules/.bin/vitest'),
      ORDESSA_VITEST_REPORTER: vitestReporter,
      ORDESSA_VITEST_CASE_LEDGER: vitestFile,
      ORDESSA_NODE_BIN: process.execPath,
      ORDESSA_NODE_REPORTER: nodeReporter,
      ORDESSA_NODE_TEST_LEDGER: nodeFile,
    })
    await Promise.all([mkdir(env.HOME, { recursive: true }), mkdir(env.TMPDIR, { recursive: true }),
      mkdir(env.npm_config_cache, { recursive: true }), writeFile(env.npm_config_userconfig, ''),
      writeFile(env.npm_config_globalconfig, '')])
    return await runNpm(root, ['run', '--workspace', 'packages/mixed-workbench', 'test'], env)
  }

  const pass = await runScenario('pass')
  assert.equal(pass.code, 0, pass.stdout + pass.stderr)
  await access(path.join(workspace, 'pre.marker'))
  await access(path.join(workspace, 'post.marker'))
  const passReports = path.join(root, 'pass')
  assert.ok((await readAndValidateReport({ kind: 'vitest-json', path: path.join(passReports, 'vitest.json'), suiteName: 'mixed pass Vitest' })).length > 0)
  assert.ok((await readAndValidateReport({ kind: 'node-event-ledger', path: path.join(passReports, 'node.json'), suiteName: 'mixed pass Node', expectedExecutionScopes: expectedScopes })).length > 0)

  const vitestFail = await runScenario('vitest-fail')
  assert.notEqual(vitestFail.code, 0)
  await assert.rejects(access(path.join(root, 'vitest-fail/node.json')))
  await assert.rejects(readAndValidateReport({ kind: 'node-event-ledger', path: path.join(root, 'vitest-fail/node.json'), suiteName: 'short-circuited Node', expectedExecutionScopes: expectedScopes }), /missing report file/)

  const nodeSkip = await runScenario('node-skip')
  assert.equal(nodeSkip.code, 0, nodeSkip.stderr)
  await assert.rejects(readAndValidateReport({ kind: 'node-event-ledger', path: path.join(root, 'node-skip/node.json'), suiteName: 'mixed Node skip', expectedExecutionScopes: expectedScopes }), /non-PASS|not all-PASS/)
})

test('Harness packaging npm adapter preserves hooks and fails on changed script', async t => {
  const root = await temporaryRoot(t, 'ordessa-js-packaging-controls-')
  const packageDir = path.join(root, 'plugins/harness/fixture/tests/packaging')
  await mkdir(packageDir, { recursive: true })
  await mkdir(path.join(root, 'owned'), { recursive: true })
  await writeFile(path.join(root, 'package.json'), JSON.stringify({ private: true, scripts: {
    'pretest:harness-packaging': "node -e \"require('node:fs').writeFileSync('owned/pre.marker','pre')\"",
    'test:harness-packaging': harnessScript,
    'posttest:harness-packaging': "node -e \"require('node:fs').writeFileSync('owned/post.marker','post')\"",
  }}))
  const fixtureTest = path.join(packageDir, 'controlled.test.mjs')
  await writeFile(fixtureTest, "import assert from 'node:assert/strict'\nimport test from 'node:test'\ntest('controlled pass', () => assert.equal(1, 1))\n")
  const expected = await resolveNodeExecutionScopes(['plugins/harness/*/tests/packaging/**/*.test.mjs'], root)
  const report = path.join(root, 'owned/node-ledger.json')
  const env = controlledEnv(root, { npm_config_script_shell: harnessShell, ORDESSA_NODE_REPORTER: nodeReporter, ORDESSA_NODE_TEST_LEDGER: report })
  await Promise.all([mkdir(env.HOME, { recursive: true }), mkdir(env.TMPDIR, { recursive: true }), mkdir(env.npm_config_cache, { recursive: true }), writeFile(env.npm_config_userconfig, ''), writeFile(env.npm_config_globalconfig, '')])
  const child = await runNpm(root, ['run', 'test:harness-packaging'], env)
  assert.equal(child.code, 0, child.stderr)
  await access(path.join(root, 'owned/pre.marker'))
  await access(path.join(root, 'owned/post.marker'))
  const cases = await readAndValidateReport({ kind: 'node-event-ledger', path: report, suiteName: 'packaging npm lifecycle', expectedExecutionScopes: expected })
  assert.ok(cases.some(row => row.id.includes('controlled pass')))

  const changed = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'))
  changed.scripts['test:harness-packaging'] += ' --test-name-pattern=filtered'
  await writeFile(path.join(root, 'package.json'), JSON.stringify(changed))
  const rejected = await runNpm(root, ['run', 'test:harness-packaging'], env)
  assert.notEqual(rejected.code, 0, 'changed command must not run without reporter instrumentation')
})


test('unknown execution command is recorded as a failed suite, not dropped', async t => {
  const root = await temporaryRoot(t, 'ordessa-js-unknown-suite-')
  const { runRecordedSuite } = await import('../checks/reported-suite-runner.mjs')
  const runRoot = path.join(root, 'runs')
  await mkdir(runRoot, { recursive: true })
  const result = await runRecordedSuite({
    suite: { name: 'node-test:unreviewed', command: ['unreviewed-test-command'] },
    rootDir: repoRoot, runRoot, ordinal: 1,
  })
  assert.equal(result.status, 'FAIL')
  assert.match(result.validationError, /no reviewed report adapter/)
  assert.equal(result.exitCode, 1)
  const stderr = await readFile(path.join(result.suiteDir, 'stderr.log'), 'utf8')
  assert.match(stderr, /no reviewed report adapter/)
  const plan = JSON.parse(await readFile(path.join(result.suiteDir, 'plan.json'), 'utf8'))
  assert.equal(plan.kind, 'unplanned')
  assert.deepEqual(plan.command, ['unreviewed-test-command'])
  assert.equal(await readFile(path.join(result.suiteDir, 'validated-cases.json'), 'utf8').then(text => JSON.parse(text).cases.length), 0)
})
