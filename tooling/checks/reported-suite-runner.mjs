import { spawn } from 'node:child_process'
import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { expectedNodeScopesForSuite } from './node-scope-caller-adapter.mjs'
import { nodeTestEntryArguments, resolveNodeExecutionScopes } from './node-execution-scopes.mjs'
import { readAndValidateReport, validateSmokeReport } from './case-ledger.mjs'

const fail = message => { throw new Error(message) }
const exists = target => access(target).then(() => true, () => false)
const isElectronSmoke = suite => suite?.name?.startsWith('electron:') === true
const isPrerequisite = suite => ['typecheck', 'build:examples', 'build:foundations', 'build:app'].includes(suite?.name)
const isHarnessPackaging = suite => suite?.name === 'node-test:plugins/harness/packaging'
const isMixedWorkbench = suite => suite?.name === 'workspace:packages/interfaces/channels/workbench/shell/workbench'

function validateCaseIds(cases, suiteName) {
  if (!Array.isArray(cases) || cases.length === 0) fail(`${suiteName}: validated result has no case rows`)
  for (const [index, item] of cases.entries()) {
    if (!item || typeof item.id !== 'string' || !item.id.trim() || item.status !== 'PASS') {
      fail(`${suiteName}: invalid validated case identity/status at row ${index}`)
    }
  }
  return cases
}

function sanitizeName(value) {
  return value.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^\.+/, '').slice(0, 100) || 'suite'
}

function scrubCredentialEnvironment(input) {
  const output = { ...input }
  for (const key of Object.keys(output)) {
    if (/TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|API[_-]?KEY|^npm_config_|^XDG_|^CODEX_HOME$|(^|_)(DATABASE_URL|DB_URL|PGHOST|PGPORT|POSTGRES_URL|MYSQL_URL|REDIS_URL|MONGO_URL|BASE_URL|ENDPOINT|SERVER_ORIGIN|SERVER_TOKEN_FILE)$/i.test(key)) delete output[key]
  }
  return output
}

async function isolatedEnvironment({ rootDir, projectRoots = [], suiteDir, extra = {} }) {
  for (const projectRoot of [rootDir, ...projectRoots]) {
    for (let current = path.resolve(projectRoot); current !== path.dirname(current); current = path.dirname(current)) {
      if (await exists(path.join(current, '.npmrc'))) {
        fail(`npm project config exists at ${current}/.npmrc; inspect it before running an isolated aggregate`)
      }
    }
  }
  const home = path.join(suiteDir, 'home')
  const tmp = path.join(suiteDir, 'tmp')
  const npmCache = path.join(suiteDir, 'npm-cache')
  const userConfig = path.join(suiteDir, 'npmrc')
  const globalConfig = path.join(suiteDir, 'global-npmrc')
  const xdgConfig = path.join(home, '.config')
  await Promise.all([home, tmp, npmCache, xdgConfig].map(dir => mkdir(dir, { recursive: true })))
  await Promise.all([
    writeFile(userConfig, 'audit=false\nfund=false\nupdate-notifier=false\n'),
    writeFile(globalConfig, ''),
  ])
  const env = scrubCredentialEnvironment(process.env)
  Object.assign(env, {
    HOME: home,
    TMPDIR: tmp,
    XDG_CONFIG_HOME: xdgConfig,
    NODE_OPTIONS: '',
    npm_config_cache: npmCache,
    npm_config_userconfig: userConfig,
    npm_config_globalconfig: globalConfig,
    npm_config_audit: 'false',
    npm_config_fund: 'false',
    npm_config_update_notifier: 'false',
    ...extra,
  })
  return env
}

function nodeReportCommand(command, reporter) {
  if (!Array.isArray(command) || command[0] !== 'node' || !command.includes('--test')) return command
  const testIndex = command.indexOf('--test')
  return [...command.slice(0, testIndex + 1), '--test-reporter', reporter, ...command.slice(testIndex + 1)]
}

function vitestReportCommand(command, reporter) {
  if (!Array.isArray(command) || !['npx', 'vitest'].includes(command[0]) || !command.includes('vitest')) return command
  return [...command, '--reporter=default', `--reporter=${reporter}`]
}

async function workspaceScript(suite, rootDir) {
  const marker = suite.command.indexOf('--workspace')
  if (suite.command[0] !== 'npm' || marker < 0 || suite.command[marker + 2] !== 'test') return null
  const rel = suite.command[marker + 1]
  const cwd = path.resolve(rootDir, rel)
  const manifestPath = path.join(cwd, 'package.json')
  if (!await exists(manifestPath)) fail(`${suite.name}: workspace manifest missing: ${manifestPath}`)
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  return { cwd, rel, script: manifest.scripts?.test }
}

export async function prepareReportedSuite({ suite, rootDir, suiteDir }) {
  if (!suite || typeof suite.name !== 'string' || !Array.isArray(suite.command) || !suite.command.length) {
    fail('invalid suite descriptor')
  }
  const reportDir = path.join(suiteDir, 'reports')
  await mkdir(reportDir, { recursive: true })
  const nodeReporter = path.join(rootDir, 'tooling/checks/node_test_event_reporter.mjs')
  const vitestReporter = path.join(rootDir, 'tooling/checks/vitest_case_ledger_reporter.mjs')
  const adapterDir = path.join(rootDir, 'tooling/checks')
  const plan = {
    originalCommand: suite.command,
    command: suite.command,
    cwd: rootDir,
    kind: 'prerequisite',
    reportFiles: [],
    expectedExecutionScopes: [],
    innerCwd: rootDir,
    environment: {},
  }
  if (isPrerequisite(suite)) return plan
  if (isElectronSmoke(suite)) {
    plan.kind = 'smoke'
    const scriptName = suite.command.at(-1)
    let manifestRoot = rootDir
    if (suite.name === 'electron:test:electron') manifestRoot = path.resolve(rootDir, 'apps/desktop')
    const manifest = JSON.parse(await readFile(path.join(manifestRoot, 'package.json'), 'utf8'))
    const script = manifest.scripts?.[scriptName]
    if (typeof script !== 'string' || !script.startsWith('node ')) fail(`${suite.name}: smoke script is missing or changed`)
    plan.innerCwd = manifestRoot
    plan.actualInnerCommand = script.split(/\s+/)
    if (plan.actualInnerCommand[0] !== 'node' || plan.actualInnerCommand.length < 2) fail(`${suite.name}: unsupported smoke node argv`)
    return plan
  }
  plan.kind = 'cases'
  if (isHarnessPackaging(suite)) {
    const expected = await expectedNodeScopesForSuite({ suite, rootDir })
    plan.expectedExecutionScopes = expected
    plan.actualInnerCommand = ['node', '--test', '--test-concurrency=1', '--test-reporter', nodeReporter, 'plugins/harness/*/tests/packaging/**/*.test.mjs']
    plan.expectedNodeExecution = { argv: plan.actualInnerCommand, cwd: rootDir, scopes: expected }
    plan.innerCwd = rootDir
    const reportPath = path.join(reportDir, 'node-event-ledger.json')
    plan.reportFiles.push({ kind: 'node-event-ledger', path: reportPath, expectedExecutionScopes: expected })
    plan.environment = {
      npm_config_script_shell: path.join(adapterDir, 'npm-harness-packaging-reporter-shell.sh'),
      ORDESSA_NODE_REPORTER: nodeReporter,
      ORDESSA_NODE_TEST_LEDGER: reportPath,
    }
    return plan
  }
  if (isMixedWorkbench(suite)) {
    const cwd = path.resolve(rootDir, 'packages/interfaces/channels/workbench/shell/workbench')
    const manifest = JSON.parse(await readFile(path.join(cwd, 'package.json'), 'utf8'))
    const script = manifest.scripts?.test
    if (script !== 'vitest run --maxWorkers=1 && node --test tests/') fail(`${suite.name}: mixed script changed; refusing instrumentation`)
    const expected = await resolveNodeExecutionScopes(['tests/'], cwd)
    const vitestPath = path.join(reportDir, 'vitest-case-ledger.json')
    const nodePath = path.join(reportDir, 'node-event-ledger.json')
    plan.cwd = rootDir
    plan.expectedExecutionScopes = expected
    plan.innerCwd = cwd
    plan.actualStages = [
      { command: ['vitest', 'run', '--maxWorkers=1', '--reporter=default', `--reporter=${vitestReporter}`], cwd },
      { command: ['node', '--test', '--test-reporter', nodeReporter, 'tests/'], cwd },
    ]
    plan.expectedNodeExecution = { argv: plan.actualStages[1].command, cwd, scopes: expected }
    plan.reportFiles.push({ kind: 'vitest-json', path: vitestPath },
                          { kind: 'node-event-ledger', path: nodePath, expectedExecutionScopes: expected })
    plan.environment = {
      npm_config_script_shell: path.join(adapterDir, 'mixed-workspace-lifecycle-shell.sh'),
      ORDESSA_MIXED_SCRIPT: script,
      ORDESSA_VITEST_BIN: path.join(rootDir, 'node_modules/.bin/vitest'),
      ORDESSA_VITEST_REPORTER: vitestReporter,
      ORDESSA_VITEST_CASE_LEDGER: vitestPath,
      ORDESSA_NODE_BIN: process.execPath,
      ORDESSA_NODE_REPORTER: nodeReporter,
      ORDESSA_NODE_TEST_LEDGER: nodePath,
    }
    return plan
  }
  const workspace = await workspaceScript(suite, rootDir)
  if (workspace) {
    plan.cwd = rootDir
    if (typeof workspace.script !== 'string' || !workspace.script.trim()) fail(`${suite.name}: missing npm test script`)
    if (workspace.script === 'vitest run' || workspace.script === 'vitest run --maxWorkers=1') {
      const reportPath = path.join(reportDir, 'vitest-case-ledger.json')
      plan.reportFiles.push({ kind: 'vitest-json', path: reportPath })
      plan.innerCwd = workspace.cwd
      plan.actualInnerCommand = workspace.script === 'vitest run'
        ? ['vitest', 'run', '--reporter=default', `--reporter=${vitestReporter}`]
        : ['vitest', 'run', '--maxWorkers=1', '--reporter=default', `--reporter=${vitestReporter}`]
      plan.environment = {
        npm_config_script_shell: path.join(adapterDir, 'npm-workspace-reporter-shell.sh'),
        ORDESSA_EXPECTED_NPM_EVENT: 'test',
        ORDESSA_EXPECTED_NPM_SCRIPT: workspace.script,
        ORDESSA_VITEST_REPORTER: vitestReporter,
        ORDESSA_VITEST_CASE_LEDGER: reportPath,
      }
      return plan
    }
    if (workspace.script === 'node --test tests/test.mjs') {
      const commandInput = ['node', ...workspace.script.split(/\s+/).slice(1)]
      const entries = nodeTestEntryArguments(commandInput)
      const expected = await resolveNodeExecutionScopes(entries, workspace.cwd)
      const reportPath = path.join(reportDir, 'node-event-ledger.json')
      plan.expectedExecutionScopes = expected
      plan.innerCwd = workspace.cwd
      plan.expectedNodeExecution = { argv: ['node', '--test', '--test-reporter', nodeReporter, ...entries], cwd: workspace.cwd, scopes: expected }
      plan.reportFiles.push({ kind: 'node-event-ledger', path: reportPath, expectedExecutionScopes: expected })
      plan.environment = {
        npm_config_script_shell: path.join(adapterDir, 'npm-workspace-reporter-shell.sh'),
        ORDESSA_EXPECTED_NPM_EVENT: 'test',
        ORDESSA_EXPECTED_NPM_SCRIPT: workspace.script,
        ORDESSA_NODE_REPORTER: nodeReporter,
        ORDESSA_NODE_TEST_LEDGER: reportPath,
      }
      plan.actualInnerCommand = ['node', '--test', '--test-reporter', nodeReporter, ...entries]
      plan.cwd = rootDir
      return plan
    }
    fail(`${suite.name}: unknown workspace test command ${JSON.stringify(workspace.script)}`)
  }
  if (suite.command[0] === 'node' && suite.command.includes('--test')) {
    const expected = await expectedNodeScopesForSuite({ suite, rootDir })
    const reportPath = path.join(reportDir, 'node-event-ledger.json')
    plan.expectedExecutionScopes = expected
    plan.reportFiles.push({ kind: 'node-event-ledger', path: reportPath, expectedExecutionScopes: expected })
    plan.command = nodeReportCommand(suite.command, nodeReporter)
    plan.actualInnerCommand = plan.command
    plan.expectedNodeExecution = { argv: plan.command, cwd: rootDir, scopes: expected }
    plan.environment = { ORDESSA_NODE_TEST_LEDGER: reportPath }
    return plan
  }
  if (suite.command[0] === 'npx' && suite.command.includes('vitest')) {
    const reportPath = path.join(reportDir, 'vitest-case-ledger.json')
    plan.reportFiles.push({ kind: 'vitest-json', path: reportPath })
    plan.command = vitestReportCommand(suite.command, vitestReporter)
    plan.actualInnerCommand = plan.command
    plan.environment = { ORDESSA_VITEST_CASE_LEDGER: reportPath }
    return plan
  }
  fail(`${suite.name}: no reviewed report adapter for ${suite.command.join(' ')}`)
}

async function spawnCapture(command, { cwd, env, stdoutPath, stderrPath }) {
  let child
  let stdout = '', stderr = ''
  try {
    child = spawn(command[0], command.slice(1), { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
  } catch (error) {
    stderr = String(error)
    await Promise.all([writeFile(stdoutPath, stdout), writeFile(stderrPath, stderr)])
    return { code: 1, stdout, stderr, spawnError: String(error) }
  }
  child.stdout.on('data', chunk => { const text = chunk.toString('utf8'); stdout += text; process.stdout.write(chunk) })
  child.stderr.on('data', chunk => { const text = chunk.toString('utf8'); stderr += text; process.stderr.write(chunk) })
  const spawnError = await new Promise(resolve => {
    child.once('error', error => resolve(String(error)))
    child.once('close', code => resolve(code ?? 1))
  })
  const code = typeof spawnError === 'number' ? spawnError : 1
  if (typeof spawnError === 'string') stderr += `\nSPAWN_ERROR ${spawnError}\n`
  await Promise.all([writeFile(stdoutPath, stdout), writeFile(stderrPath, stderr)])
  return { code, stdout, stderr, spawnError: typeof spawnError === 'string' ? spawnError : null }
}

export async function runRecordedSuite({ suite, rootDir, runRoot, ordinal }) {
  const suiteDir = path.join(runRoot, `${String(ordinal).padStart(2, '0')}-${sanitizeName(suite.name)}`)
  await mkdir(suiteDir, { recursive: true })
  const raw = { plan: path.join(suiteDir, 'plan.json'), stdout: path.join(suiteDir, 'stdout.log'), stderr: path.join(suiteDir, 'stderr.log'), exit: path.join(suiteDir, 'exit.json') }
  const record = { suite: suite.name, originalCommand: suite.command, suiteDir, status: 'FAIL', cases: [], validationError: null }
  try {
    const plan = await prepareReportedSuite({ suite, rootDir, suiteDir })
    record.plan = { kind: plan.kind, command: plan.command, actualInnerCommand: plan.actualInnerCommand ?? null, actualStages: plan.actualStages ?? null, expectedNodeExecution: plan.expectedNodeExecution ?? null, cwd: plan.cwd, innerCwd: plan.innerCwd,
      expectedExecutionScopes: plan.expectedExecutionScopes, reportFiles: plan.reportFiles.map(item => ({ ...item })),
      npmScript: plan.environment.ORDESSA_EXPECTED_NPM_SCRIPT ?? plan.environment.ORDESSA_MIXED_SCRIPT ?? null }
    await writeFile(raw.plan, `${JSON.stringify(record.plan, null, 2)}\n`)
    const env = await isolatedEnvironment({ rootDir, projectRoots: [plan.innerCwd ?? plan.cwd], suiteDir, extra: plan.environment })
    const child = await spawnCapture(plan.command, { cwd: plan.cwd, env, stdoutPath: raw.stdout, stderrPath: raw.stderr })
    record.exitCode = child.code
    record.spawnError = child.spawnError
    if (child.code !== 0) record.validationError = `child exited ${child.code}`
    if (plan.kind === 'cases') {
      for (const attachment of plan.reportFiles) {
        try {
          const cases = validateCaseIds(await readAndValidateReport({ ...attachment, suiteName: suite.name }), suite.name)
          record.cases.push(...cases.map(item => ({ ...item, attachment: path.basename(attachment.path) })))
        } catch (error) {
          record.validationError ??= String(error?.stack ?? error)
        }
      }
      if (!record.cases.length) record.validationError ??= `${suite.name}: no cases validated`
    } else if (plan.kind === 'smoke') {
      try { record.cases = validateCaseIds(validateSmokeReport(suite.name, child.code, child.stdout, child.stderr), suite.name) }
      catch (error) { record.validationError ??= String(error?.stack ?? error) }
    } else if (child.code === 0) {
      record.status = 'PREREQUISITE_OK_NO_CASE_CLAIM'
    }
    if (plan.kind !== 'prerequisite') record.status = child.code === 0 && !record.validationError ? 'PASS' : 'FAIL'
  } catch (error) {
    record.validationError = String(error?.stack ?? error)
    record.exitCode ??= 1
    // A planning/configuration error is itself an explicit failed suite record.
    record.plan = { kind: 'unplanned', command: suite.command, actualInnerCommand: null, actualStages: null,
      expectedNodeExecution: null, cwd: rootDir, innerCwd: null, expectedExecutionScopes: [], reportFiles: [],
      planningFailure: record.validationError }
    await writeFile(raw.plan, `${JSON.stringify(record.plan, null, 2)}\n`)
    await writeFile(raw.stdout, '')
    await writeFile(raw.stderr, `${record.validationError}\n`)
  }
  await writeFile(raw.exit, `${JSON.stringify({ suite: suite.name, code: record.exitCode ?? 1, status: record.status, raw, validationError: record.validationError }, null, 2)}\n`)
  await writeFile(path.join(suiteDir, 'validated-cases.json'), `${JSON.stringify({ suite: suite.name, status: record.status, cases: record.cases, validationError: record.validationError }, null, 2)}\n`)
  return record
}

export async function createRunRoot(rootDir) {
  const cacheRoot = path.join(rootDir, '.nightly-cache/js-aggregate-caller/runs')
  await mkdir(cacheRoot, { recursive: true })
  return await import('node:fs/promises').then(({ mkdtemp }) => mkdtemp(path.join(cacheRoot, 'run-')))
}
