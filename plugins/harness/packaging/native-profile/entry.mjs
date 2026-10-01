#!/usr/bin/env node
// Establish instance scope before evaluating any upstream module. This is
// configuration isolation, not a sandbox or a per-Profile home directory.
import { lstatSync, realpathSync } from 'node:fs'
import path from 'node:path'

try {
  const directory = process.env.ORDESSA_NATIVE_INSTANCE_DIR
  if (!directory || !path.isAbsolute(directory) || path.normalize(directory) !== directory)
    throw new Error('invalid instance scope')
  const stat = lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink() || realpathSync(directory) !== directory
      || stat.uid !== process.getuid() || (stat.mode & 0o077) !== 0)
    throw new Error('invalid instance ownership')
  // The backend owner allocates a unique private directory. Never implicitly
  // copy login/configuration from the user's HOME or create through symlinks.
  process.env.HOME = directory
  process.env.CODEX_HOME = directory
  process.env.CLAUDE_CONFIG_DIR = directory
  process.env.XDG_CONFIG_HOME = directory
} catch {
  // Closed diagnostic: no user paths, credentials or upstream errors.
  console.error('Native Profile startup refused: private instance directory required')
  process.exit(1)
}
await import('./index.js')
