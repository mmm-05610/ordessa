// Same node v22.22.1 `node --test <dir>` quirk workaround as
// packages/workbench/tests/index.js: `node --test products/desktop/tests/`
// resolves this index, which imports every *.test.mjs in the directory so
// future product suites (T021+) are picked up automatically.
import { readdir } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

for (const entry of (await readdir(import.meta.dirname)).sort()) {
  if (entry.endsWith('.test.mjs')) await import(pathToFileURL(path.join(import.meta.dirname, entry)).href)
}
