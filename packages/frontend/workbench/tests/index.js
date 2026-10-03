// Node v22.22.1 quirk (registered in plugins/harness/TEST-REVIEW.md):
// `node --test <dir>` resolves the directory as a module entry instead of
// discovering test files, so this index re-exports every *.test.mjs in this
// directory. New suites (T020/T021) are picked up automatically.
import { readdir } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

for (const entry of (await readdir(import.meta.dirname)).sort()) {
  if (entry.endsWith('.test.mjs')) await import(pathToFileURL(path.join(import.meta.dirname, entry)).href)
}
