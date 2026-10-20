import { glob, lstat } from 'node:fs/promises'
import path from 'node:path'

const fail = message => { throw new Error(message) }

/**
 * Resolve the exact Node --test entry arguments before launch. `entries` must
 * come from the reviewed argv/script adapter, never from the suite's probe list.
 * Direct directory entries remain directories: Node 22.22 reports the
 * directory as the execution summary scope even when its index.js imports
 * sibling test modules.
 */
export async function resolveNodeExecutionScopes(entries, cwd) {
  if (!Array.isArray(entries) || entries.length === 0 || typeof cwd !== 'string' || !path.isAbsolute(cwd)) {
    fail('expected Node entries and an absolute working directory are required')
  }
  const scopes = []
  for (const entry of entries) {
    if (typeof entry !== 'string' || !entry) fail('invalid empty Node test entry')
    const matches = ['*', '?', '{', '['].some(marker => entry.includes(marker))
      ? await collectGlobMatches(entry, cwd)
      : [path.resolve(cwd, entry)]
    if (!matches.length) fail(`Node test entry matched nothing: ${entry}`)
    for (const match of matches) {
      const resolved = path.resolve(cwd, match)
      const stat = await lstat(resolved)
      if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory())) {
        fail(`unsupported Node test entry type: ${resolved}`)
      }
      scopes.push(resolved)
    }
  }
  if (!scopes.length) fail('Node entry expansion is empty')
  if (new Set(scopes).size !== scopes.length) fail(`Node argv resolves duplicate entry scopes: ${JSON.stringify(scopes)}`)
  return scopes
}

async function collectGlobMatches(pattern, cwd) {
  const matches = []
  for await (const match of glob(pattern, { cwd })) matches.push(match)
  return matches
}

/** Extract positional --test entries from current reviewed argv shapes. */
export function nodeTestEntryArguments(command) {
  if (!Array.isArray(command) || command[0] !== 'node') fail(`not a reviewed Node command: ${String(command)}`)
  const testIndex = command.indexOf('--test')
  if (testIndex < 0) fail(`Node command lacks --test: ${command.join(' ')}`)
  const args = command.slice(testIndex + 1)
  const entries = args.filter(argument => !argument.startsWith('-'))
  if (!entries.length) fail(`Node command has no --test entry: ${command.join(' ')}`)
  return entries
}
