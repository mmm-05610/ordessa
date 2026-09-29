/**
 * C-02 §6 — where the Server's executable lives, resolved before anything is
 * spawned.
 *
 * The order is fixed: `ORDESSA_BUNDLED_ROOT` for a development tree, then the
 * installed layout under `/opt/ordessa`. The check is a completeness check,
 * not an existence check: `bin/acp` deleted from an otherwise intact install
 * must fail HERE, before a Server is started, because a host that has
 * already spawned a process cannot honestly present the result as a refusal
 * rather than as a half-working application.
 *
 * Nothing in this file names a brand or a product. It resolves directories
 * and one bridge binary, and reports what is missing by relative path.
 */
import { existsSync, statSync } from 'node:fs'
import path from 'node:path'

import { layout } from './data-root.js'
import { BundledRuntimeMissing } from './errors.js'

export interface BundledRuntime {
  /** The root the three directories were found under. */
  readonly root: string
  /** The interpreter that runs `python -m ordessa_server`. */
  readonly python: string
  /** The bin directory, holding the ACP bridge. */
  readonly bin: string
  /** Where per-Harness artifacts are read from. */
  readonly harnesses: string
  /** The ACP bridge executable. */
  readonly acpBridge: string
}

function isDirectory(candidate: string): boolean {
  try {
    return statSync(candidate).isDirectory()
  } catch {
    return false
  }
}

function isFile(candidate: string): boolean {
  try {
    return statSync(candidate).isFile()
  } catch {
    return false
  }
}

/**
 * Resolve the bundled runtime, or refuse with the missing items named.
 *
 * `missing` holds RELATIVE names (`bin/acp`, not `/opt/ordessa/bin/acp`). A
 * refusal that quoted the full path would put an install layout into a user
 * facing message, and the remedy does not need it.
 */
export function resolveBundledRuntime(
  env: Readonly<Record<string, string | undefined>> = process.env,
): BundledRuntime {
  const launch = layout().launch
  const root = env[launch.bundledRootEnv] ?? launch.bundledRootDefault
  const python = path.join(root, 'python')
  const bin = path.join(root, 'bin')
  const harnesses = path.join(root, 'harnesses')
  const acpBridge = path.join(root, launch.acpBridgeRelative)

  const missing: string[] = []
  if (!isDirectory(python)) missing.push('python')
  if (!isDirectory(bin)) missing.push('bin')
  else if (!isFile(acpBridge)) missing.push(launch.acpBridgeRelative)
  if (!isDirectory(harnesses)) missing.push('harnesses')
  if (missing.length > 0) throw new BundledRuntimeMissing(missing)

  return { root, python, bin, harnesses, acpBridge }
}

/** The command that starts the Server: the bundled interpreter, this module's package. */
export function serverCommand(runtime: BundledRuntime): readonly string[] {
  return [runtime.python, '-m', 'ordessa_server']
}

/** Is a bundled root present at all? A cheaper pre-check for the settings page. */
export function bundledRootExists(
  env: Readonly<Record<string, string | undefined>> = process.env,
): boolean {
  const launch = layout().launch
  return existsSync(env[launch.bundledRootEnv] ?? launch.bundledRootDefault)
}
