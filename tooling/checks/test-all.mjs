// T021: the root JS test entry really aggregates every JS suite of this repo instead of
// pointing at one package. Every suite runs even after a failure and keeps its own exit
// code; workspace packages that carry a `test` script are discovered and must all appear;
// the non-workspace roots are presence-checked; prerequisites (typecheck, real builds)
// run first because the Electron gates read built output. Nothing here starts the real
// Server, calls a real model, or touches run data — the gates drive fake/loopback peers.
import { writeFile } from 'node:fs/promises'
import { access, readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRunRoot, runRecordedSuite } from './reported-suite-runner.mjs'

const repoRoot = path.resolve(process.env.ORDESSA_REPO_ROOT ?? path.resolve(import.meta.dirname, '../..'))
const SKIP_PACKAGE_DISCOVERY = new Set(['node_modules', 'dist', 'design-source', 'worktree'])

function patternToRegExp(pattern) {
  const source = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*/g, '\u0001')
    .replace(/\*/g, '[^/]+')
    .replace(/\u0001/g, '.*')
  return new RegExp(`^${source}$`)
}

const exists = dir => access(dir).then(() => true, () => false)

/** Find package manifests below rootDir, excluding vendored/build/design inputs. */
export async function packageDirs(rootDir = repoRoot) {
  const found = []

  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith('.') || SKIP_PACKAGE_DISCOVERY.has(entry.name)) continue
      const dir = path.join(current, entry.name)
      const rel = path.relative(rootDir, dir).split(path.sep).join('/')
      if (await exists(path.join(dir, 'package.json'))) found.push(rel)
      await visit(dir)
    }
  }

  await visit(rootDir)
  return found
}

/** Every workspace package that declares its own `test` script. */
export async function discoveredWorkspaceSuites(rootDir = repoRoot) {
  const manifest = JSON.parse(await readFile(path.join(rootDir, 'package.json'), 'utf8'))
  const patterns = manifest.workspaces ?? []
  const include = patterns.filter(p => !p.startsWith('!')).map(patternToRegExp)
  const exclude = patterns.filter(p => p.startsWith('!')).map(p => patternToRegExp(p.slice(1)))
  const found = []
  for (const rel of await packageDirs(rootDir)) {
    if (!include.some(re => re.test(rel)) || exclude.some(re => re.test(rel))) continue
    const pkg = JSON.parse(await readFile(path.join(rootDir, rel, 'package.json'), 'utf8'))
    if (pkg.scripts?.test) found.push({ name: `workspace:${rel}`, command: ['npm', 'run', '--workspace', rel, 'test'] })
  }
  return found.sort((a, b) => a.name.localeCompare(b.name))
}

const PREREQUISITES = [
  { name: 'typecheck', command: ['npm', 'run', 'typecheck'] },
  { name: 'build:examples', command: ['npm', 'run', 'build:examples'] },
  { name: 'build:foundations', command: ['npm', 'run', 'build:foundations'] },
  { name: 'build:app', command: ['npm', 'run', 'build'] },
]

// Roots that are not npm workspaces with a test script: the product guard and the ACP
// rig (its own package.json + lockfile). Presence-checked below so a moved suite fails
// loudly instead of dropping out of the aggregate.
const EXTRA_ROOTS = [
  { name: 'vitest:integration/agents/connectors', probes: [
    'tests/integration/agents/connectors/acp/agent-acp-wiring.test.ts',
    'tests/integration/agents/connectors/acp/native-commands.test.ts',
    'tests/integration/agents/connectors/ordessa/agent-ordessa-connector.test.ts',
  ], command: ['npx', 'vitest', 'run', '--root', 'tests/integration/agents/connectors'] },
  { name: 'node-test:tooling', probes: ['tooling/tests/test-all.test.mjs', 'tooling/tests/dependency-boundaries.test.mjs', 'tooling/tests/build-extension-shared-api.test.mjs', 'tooling/tests/native_profiles/configuration.test.mjs', 'tooling/tests/harness_packaging/model-validation-42d.test.mjs'], command: ['node', '--test', 'tooling/tests/**/*.test.mjs'] },
  { name: 'node-test:apps/desktop/packaging/product', probe: 'apps/desktop/tests/product', command: ['node', '--test', 'apps/desktop/tests/product/'] },
  { name: 'node-test:plugins/harness/packaging', probes: [
    'plugins/harness/claude-code/tests/packaging/claude_legacy_lock.test.mjs',
    'plugins/harness/claude-code/tests/packaging/provider-session.test.mjs',
    'plugins/harness/codex/tests/packaging/build-codex-runtime-artifact.test.mjs',
    'plugins/harness/dsh/tests/packaging/build-dsh-runtime-artifact.test.mjs',
    'plugins/harness/hermes/tests/packaging/build-hermes-runtime-artifact.test.mjs',
    'plugins/harness/kilo/tests/packaging/build-kilo-runtime-artifact.test.mjs',
    'plugins/harness/opencode/tests/packaging/build-opencode-authorization.test.mjs',
    'plugins/harness/opencode/tests/packaging/build-opencode-runtime-artifact.test.mjs',
    'plugins/harness/pi/tests/packaging/build-pi-runtime-artifact.test.mjs',
  ], command: ['npm', 'run', 'test:harness-packaging'] },
  {"name": "node-test:claude-code/acp", "probes": ["plugins/harness/claude-code/tests/acp/claude-auth.test.mjs", "plugins/harness/claude-code/tests/acp/claude-provider-model.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "plugins/harness/claude-code/tests/acp/claude-auth.test.mjs", "plugins/harness/claude-code/tests/acp/claude-provider-model.test.mjs"]},
  {"name": "node-test:codex/acp", "probes": ["plugins/harness/codex/tests/acp/codex-model-catalog.test.mjs", "plugins/harness/codex/tests/acp/codex-process.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "plugins/harness/codex/tests/acp/codex-model-catalog.test.mjs", "plugins/harness/codex/tests/acp/codex-process.test.mjs"]},
  {"name": "node-test:pi/acp", "probes": ["plugins/harness/pi/tests/acp/configuration-operation.test.mjs", "plugins/harness/pi/tests/acp/configuration-query.test.mjs", "plugins/harness/pi/tests/acp/creation.test.mjs", "plugins/harness/pi/tests/acp/entry.test.mjs", "plugins/harness/pi/tests/acp/provider-registration.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "plugins/harness/pi/tests/acp/configuration-operation.test.mjs", "plugins/harness/pi/tests/acp/configuration-query.test.mjs", "plugins/harness/pi/tests/acp/creation.test.mjs", "plugins/harness/pi/tests/acp/entry.test.mjs", "plugins/harness/pi/tests/acp/provider-registration.test.mjs"]},
  {"name": "node-test:opencode/transport", "probes": ["plugins/harness/opencode/tests/opencode_abort_outcome_halfb.test.mjs", "plugins/harness/opencode/tests/opencode_control_leg_audit.test.mjs", "plugins/harness/opencode/tests/opencode_driver_tail.test.mjs", "plugins/harness/opencode/tests/opencode_pump_attribution_x20.test.mjs", "plugins/harness/opencode/tests/opencode_stream_framing.test.mjs", "plugins/harness/opencode/tests/opencode_subscriber_attribution.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "plugins/harness/opencode/tests/opencode_abort_outcome_halfb.test.mjs", "plugins/harness/opencode/tests/opencode_control_leg_audit.test.mjs", "plugins/harness/opencode/tests/opencode_driver_tail.test.mjs", "plugins/harness/opencode/tests/opencode_pump_attribution_x20.test.mjs", "plugins/harness/opencode/tests/opencode_stream_framing.test.mjs", "plugins/harness/opencode/tests/opencode_subscriber_attribution.test.mjs"]},
  {"name": "node-test:agents/harness-transport", "probes": ["packages/execution/agents/tests/agents/harness_transport/frame_buffer_lifecycle.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "packages/execution/agents/tests/agents/harness_transport/frame_buffer_lifecycle.test.mjs"]},
  {"name": "node-test:apps/server/harness", "probes": ["apps/server/tests/integration/harness/access_entry_staging.test.mjs", "apps/server/tests/integration/harness/capability_claims.test.mjs", "apps/server/tests/integration/harness/launch_descriptors.test.mjs", "apps/server/tests/support/controlled_peer_allowlist.test.mjs"], "command": ["node", "--test", "--test-concurrency=1", "apps/server/tests/integration/harness/access_entry_staging.test.mjs", "apps/server/tests/integration/harness/capability_claims.test.mjs", "apps/server/tests/integration/harness/launch_descriptors.test.mjs", "apps/server/tests/support/controlled_peer_allowlist.test.mjs"]},
  // Exact current owner and fixture probes keep every migrated access case visible.
  { name: 'node-test:tests/integration/harness/access', probes: [
    'tests/integration/harness/access/access_entry_behavior.test.mjs',
    'tests/integration/harness/access/access_launch_route.test.mjs',
    'tests/integration/harness/access/acp_channel_behavior.test.mjs',
    'tests/integration/harness/access/acp_passthrough_target.test.mjs',
    'tests/integration/harness/access/controlled_harness_self_proof.test.mjs',
    'tests/integration/harness/access/native_installed_artifact.test.mjs',
    'tests/integration/harness/access/real_adapter_protocol.test.mjs',
    'tests/fixtures/harness/access/controlled_harness.mjs',
    'tests/fixtures/harness/access/fixture_child_marker.mjs',
    'tests/integration/harness/access/support/sidecar_harness.mjs',
  ], command: ['node', '--test', 'tests/integration/harness/access/**/*.test.mjs'] },
  // The frozen open-environment TS contract mirror (spec 026/002) and the
  // foundation token-identity gate. The token-identity test had also never
  // run in an aggregate before this entry — same defect class as the access
  // row above, found while wiring the contract freeze.
  { name: 'node-test:packages/interfaces/channels/workbench/extension-api/contracts', probe: 'packages/interfaces/channels/workbench/extension-api/contracts/foundation/open-environment.test.mjs', command: ['node', '--test', 'packages/interfaces/channels/workbench/extension-api/contracts/**/*.test.mjs'] },
  // 008-T008-20: the two independent F5 fixture packages run in the
  // aggregate through their real package entries (examples are independent
  // build inputs, but their tests are gate evidence like any suite).
  { name: 'node-test:examples/f5-counter', probe: 'examples/plugins/external-samples/f5-counter/tests/test.mjs', command: ['node', '--test', 'examples/plugins/external-samples/f5-counter/tests/test.mjs'] },
  { name: 'vitest:examples/f5-react-panel', probe: 'examples/plugins/external-samples/f5-react-panel/tests/panel.test.tsx', command: ['npx', 'vitest', 'run', '--root', 'examples/plugins/external-samples/f5-react-panel'] },
  { name: 'rig:tests/integration/acp-connector', probe: 'tests/integration/acp-connector', command: ['npx', 'vitest', 'run', '--root', 'tests/integration/acp-connector'] },
]

const ELECTRON_GATES = ['test:electron', 'test:extensions', 'test:agent-ui', 'test:agent-shell', 'test:ui-service', 'test:ui-foundations', 'test:ui-preview']
  .map(name => ({ name: `electron:${name}`, command: ['npm', 'run', name] }))

export function selectSuites(suites, filter) {
  return suites.filter(suite => !filter || suite.name.includes(filter))
}

/** Return missing required roots, exported so fixture tests can pin fail-closed discovery. */
export async function missingRequiredRoots(rootDir = repoRoot, requiredRoots = EXTRA_ROOTS) {
  const missing = []
  for (const suite of requiredRoots) {
    for (const probe of suite.probes ?? [suite.probe]) {
      if (!await exists(path.join(rootDir, probe))) missing.push(`${suite.name} → ${probe}`)
    }
  }
  return missing
}

export async function main({ rootDir = repoRoot, argv = process.argv.slice(2) } = {}) {
  const unknownOptions = argv.filter(arg => arg.startsWith('-') && arg !== '--list')
  if (unknownOptions.length) throw Error(`unsupported aggregate option(s): ${unknownOptions.join(', ')}`)
  const positional = argv.filter(arg => arg !== '--list')
  if (positional.length > 1) throw Error(`expected at most one suite filter, got ${positional.length}`)
  const filter = positional[0]
  const workspaces = await discoveredWorkspaceSuites(rootDir)
  if (workspaces.length < 4) throw Error(`discovered only ${workspaces.length} workspace test suites — the pattern matcher or the ` +
    'workspace `test` scripts regressed, and an empty aggregate would pass vacuously')

  const missing = await missingRequiredRoots(rootDir)
  if (missing.length) throw Error(`aggregated roots are gone (a moved suite must be re-declared, not dropped): ${missing.join(', ')}`)

  const allSuites = [...PREREQUISITES, ...workspaces, ...EXTRA_ROOTS, ...ELECTRON_GATES]
  const inventory = JSON.parse(await readFile(new URL('./aggregate-suite-inventory.json', import.meta.url), 'utf8'))
  if (inventory.schema !== 'ordessa.js.aggregate-suite-inventory.v1' || inventory.count !== 53 || inventory.suites.length !== 53) {
    throw Error('checked-in aggregate suite inventory is malformed; refusing a partial gate')
  }
  const actualInventory = allSuites.map(suite => ({ name: suite.name, command: suite.command }))
  const expectedInventory = inventory.suites.map(item => ({ name: item.name, command: item.command }))
  if (JSON.stringify(actualInventory) !== JSON.stringify(expectedInventory)) {
    throw Error(`aggregate suite inventory changed; review additions/removals/commands explicitly\nexpected=${JSON.stringify(expectedInventory)}\nactual=${JSON.stringify(actualInventory)}`)
  }
  const suites = selectSuites(allSuites, filter)
  if (!suites.length) throw Error(`no suite matches filter ${JSON.stringify(filter)} — nothing was verified`)

  // `--list` prints what would run without running it, so the aggregate itself can be
  // audited (which suites are covered) without paying for a full gate cycle.
  if (argv.includes('--list')) {
    console.log(suites.map(s => `${s.name}  ${s.command.join(' ')}`).join('\n'))
    console.log(`${suites.length} suites`)
    return
  }

  const runRoot = await createRunRoot(rootDir)
  await writeFile(path.join(runRoot, 'run.json'), `${JSON.stringify({
    schema: 'ordessa.js.aggregate-run.v1',
    rootDir,
    selectedSuites: suites.map(suite => ({ name: suite.name, command: suite.command })),
    totalInventory: inventory.count,
    filtered: Boolean(filter),
    filter: filter ?? null,
  }, null, 2)}\n`)
  const results = []
  for (const [index, suite] of suites.entries()) {
    console.log(`\n\u001b[1m▶ ${suite.name}\u001b[0m ${suite.command.join(' ')}`)
    const result = await runRecordedSuite({ suite, rootDir, runRoot, ordinal: index + 1 })
    results.push(result)
  }

  console.log('\n===== root JS aggregation summary =====')
  for (const result of results) {
    const caseCount = result.cases?.length ?? 0
    const label = result.status === 'PASS' ? 'PASS' : result.status === 'PREREQUISITE_OK_NO_CASE_CLAIM' ? 'GATE_OK_NO_CASE_CLAIM' : 'FAIL'
    console.log(`${label} exit=${result.exitCode ?? 1} cases=${caseCount} ${result.suite}`)
  }
  const failed = results.filter(result => result.status === 'FAIL')
  const validatedCases = results.flatMap(result => (result.cases ?? []).map(item => ({ suite: result.suite, ...item })))
  const summary = {
    schema: 'ordessa.js.aggregate-summary.v1',
    selectedSuiteCount: suites.length,
    inventorySuiteCount: inventory.count,
    validatedCaseCount: validatedCases.length,
    passedCaseSuites: results.filter(result => result.status === 'PASS').length,
    successfulPrerequisiteGates: results.filter(result => result.status === 'PREREQUISITE_OK_NO_CASE_CLAIM').length,
    failedSuites: failed.map(result => ({ suite: result.suite, exitCode: result.exitCode ?? 1, reason: result.validationError })),
    cases: validatedCases,
    status: failed.length ? 'FAIL' : 'PASS',
  }
  await writeFile(path.join(runRoot, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`)
  const accepted = summary.passedCaseSuites + summary.successfulPrerequisiteGates
  console.log(`\n${accepted}/${summary.selectedSuiteCount} suites accepted (${summary.passedCaseSuites} case suites, ${summary.successfulPrerequisiteGates} prerequisite gates with no case claim); ${summary.validatedCaseCount} validated cases; report=${runRoot}`)
  if (failed.length) process.exitCode = 1
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
