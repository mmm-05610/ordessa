import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { nodeTestEntryArguments, resolveNodeExecutionScopes } from './node-execution-scopes.mjs'

const HARNESS_PACKAGING_SCRIPT = 'mkdir -p .nightly-cache/harness-test-tmp && TMPDIR="${TMPDIR:-$PWD/.nightly-cache/harness-test-tmp}" node --test --test-concurrency=1 "plugins/harness/*/tests/packaging/**/*.test.mjs"'
const WORKBENCH_SCRIPT = 'vitest run --maxWorkers=1 && node --test tests/'
const WORKBENCH_PATH = 'packages/interfaces/channels/workbench/shell/workbench'
const HARNESS_PACKAGING_PATTERN = 'plugins/harness/*/tests/packaging/**/*.test.mjs'

/** Resolve Node execution scopes from reviewed command/package-script inputs before launch. */
export async function expectedNodeScopesForSuite({ suite, rootDir }) {
  if (!suite || typeof suite.name !== 'string' || !Array.isArray(suite.command)) throw new Error('invalid suite descriptor')

  if (suite.name === 'node-test:plugins/harness/packaging') {
    if (JSON.stringify(suite.command) !== JSON.stringify(['npm', 'run', 'test:harness-packaging'])) {
      throw new Error('Harness packaging npm command changed; reporter adapter needs review')
    }
    const rootPackage = JSON.parse(await readFile(path.join(rootDir, 'package.json'), 'utf8'))
    if (rootPackage.scripts?.['test:harness-packaging'] !== HARNESS_PACKAGING_SCRIPT) {
      throw new Error('test:harness-packaging script changed; refusing Node scope guess')
    }
    return resolveNodeExecutionScopes([HARNESS_PACKAGING_PATTERN], rootDir)
  }

  if (suite.name === `workspace:${WORKBENCH_PATH}`) {
    const expectedCommand = ['npm', 'run', '--workspace', WORKBENCH_PATH, 'test']
    if (JSON.stringify(suite.command) !== JSON.stringify(expectedCommand)) throw new Error('Workbench npm command changed')
    const workspaceRoot = path.resolve(rootDir, WORKBENCH_PATH)
    const manifest = JSON.parse(await readFile(path.join(workspaceRoot, 'package.json'), 'utf8'))
    if (manifest.scripts?.test !== WORKBENCH_SCRIPT) throw new Error('Workbench Node entry script changed')
    return resolveNodeExecutionScopes(['tests/'], workspaceRoot)
  }

  if (suite.command[0] === 'node' && suite.command.includes('--test')) {
    return resolveNodeExecutionScopes(nodeTestEntryArguments(suite.command), rootDir)
  }

  return null
}
