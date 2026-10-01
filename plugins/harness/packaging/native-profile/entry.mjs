#!/usr/bin/env node
// Establish instance scope before evaluating any upstream module. This is
// configuration isolation, not a sandbox or a per-Profile home directory.
import { lstatSync, realpathSync } from 'node:fs'
import path from 'node:path'

// Replaced by the verified artifact builder, not by a runtime brand flag.
const brand = '__ORDESSA_NATIVE_BRAND__'

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
  const account = process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR
  if (account !== undefined) {
    if (brand !== 'codex' || !account || !path.isAbsolute(account)
        || path.normalize(account) !== account || account.endsWith(path.sep))
      throw new Error('invalid account scope')
    const info = lstatSync(account)
    if (!info.isDirectory() || info.isSymbolicLink() || realpathSync(account) !== account
        || info.uid !== process.getuid() || (info.mode & 0o077) !== 0
        || account === directory || account.startsWith(directory + path.sep)
        || directory.startsWith(account + path.sep))
      throw new Error('invalid account ownership')
    process.env.CODEX_HOME = account
  }
  if (brand === 'codex') {
    // Authentication always comes from explicit backend preparation or the
    // selected managed keyring scope, never inherited shell credentials.
    for (const key of ['CODEX_API_KEY', 'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN',
      'CODEX_AUTH_TOKEN', 'DEFAULT_AUTH_REQUEST', 'MODEL_PROVIDER']) delete process.env[key]
  }
} catch {
  // Closed diagnostic: no user paths, credentials or upstream errors.
  console.error('Native Profile startup refused: private instance directory required')
  process.exit(1)
}
await import('./index.js')
