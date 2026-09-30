#!/usr/bin/env node
// Reserve stdout before evaluating upstream dependencies, as upstream does.
import { lstatSync, realpathSync } from 'node:fs'
import path from 'node:path'
for (const name of ['log', 'info', 'warn', 'debug']) console[name] = console.error
try {
  const directory = process.env.ORDESSA_PI_INSTANCE_DIR
  if (!directory || !path.isAbsolute(directory) || path.normalize(directory) !== directory)
    throw new Error('ORDESSA_PI_INSTANCE_DIR must be a canonical absolute private directory')
  // The session owner must allocate the directory first. Do not create a
  // directory through possibly-symlinked ancestors before checking its path.
  const stat = lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink() || realpathSync(directory) !== directory
      || stat.uid !== process.getuid() || (stat.mode & 0o077) !== 0)
    throw new Error('Pi instance directory must be owned by this user, private and symlink-free')
  // Set before dynamic imports: auth, models, settings and sessions all use
  // this instance, not ~/.pi/agent. No credentials are copied implicitly.
  process.env.PI_CODING_AGENT_DIR = directory
  process.env.PI_CODING_AGENT_SESSION_DIR = path.join(directory, 'sessions')
  const { runAcp } = await import('./ordessa-profile-server.mjs')
  const { connection, agent } = await runAcp({ deps: { agentDir: directory,
    sessionDir: path.join(directory, 'sessions') } })
  let stopping
  const shutdown = code => stopping ??= (async () => {
    const timeout = setTimeout(() => process.exit(1), 66_000)
    try { await agent.dispose(); clearTimeout(timeout); process.exit(code) }
    catch { clearTimeout(timeout); console.error('Pi instance cleanup failed'); process.exit(1) }
  })()
  connection.closed.then(() => shutdown(0), () => shutdown(1))
  process.on('SIGTERM', () => { void shutdown(0) })
  process.on('SIGINT', () => { void shutdown(0) })
  process.stdin.resume()
} catch (error) {
  console.error('Pi profile bridge startup refused:', error.message)
  process.exit(1)
}
