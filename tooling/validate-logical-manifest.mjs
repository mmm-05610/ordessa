#!/usr/bin/env node
/**
 * Validate logical plugin manifests (plugin.manifest.json) against the
 * schema frozen at 002 (evidence/contracts/domain-paths.json:
 * logicalManifestSchema). The logical manifest is BUILD-TIME metadata only:
 * it is not a third host — products/extensions.json and the runtime
 * manifests remain the selection/scheduling authority, and the validator
 * refuses anything that would turn a manifest into a scheduler.
 */
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const CATEGORIES = ['harness', 'agent', 'chat', 'profile', 'model-provider', 'workspace', 'resource', 'service', 'environment', 'platform']
const ARTIFACT_KINDS = ['npm', 'wheel', 'bundle', 'assets']
const EXECUTION_DOMAINS = ['frontend', 'backend']
const FORBIDDEN_KEYS = ['enable', 'enabled', 'startup', 'start', 'activate', 'registry', 'scheduler', 'dispatch']

export function validateLogicalManifest(manifest, fileLabel = 'plugin.manifest.json') {
  const errors = []
  const err = message => errors.push(`${fileLabel}: ${message}`)

  for (const key of Object.keys(manifest)) {
    if (FORBIDDEN_KEYS.includes(key)) {
      err(`forbidden key '${key}' — a logical manifest is a catalog, not a scheduler`)
    }
  }
  const allowed = new Set(['schemaVersion', 'logicalPluginId', 'displayName', 'categories', 'versionSource', 'artifacts', 'entries'])
  for (const key of Object.keys(manifest)) {
    if (!allowed.has(key)) err(`unknown key '${key}'`)
  }

  if (manifest.schemaVersion !== 1) err(`schemaVersion must be 1, got ${JSON.stringify(manifest.schemaVersion)}`)
  if (typeof manifest.logicalPluginId !== 'string' || !/^[a-z][a-z0-9.-]{1,63}$/.test(manifest.logicalPluginId)) {
    err(`logicalPluginId is malformed: ${JSON.stringify(manifest.logicalPluginId)}`)
  }
  if (typeof manifest.displayName !== 'string' || manifest.displayName.length === 0) err('displayName is required')
  if (!Array.isArray(manifest.categories) || manifest.categories.some(c => !CATEGORIES.includes(c))) {
    err(`categories must be drawn from ${CATEGORIES.join('|')}`)
  }
  if (typeof manifest.versionSource !== 'string' || manifest.versionSource.length === 0) err('versionSource is required')

  if (!Array.isArray(manifest.artifacts)) err('artifacts must be an array')
  else for (const [i, a] of manifest.artifacts.entries()) {
    if (!a || !ARTIFACT_KINDS.includes(a.kind)) err(`artifacts[${i}].kind must be one of ${ARTIFACT_KINDS.join('|')}`)
    if (typeof a?.path !== 'string' || a.path.length === 0) err(`artifacts[${i}].path is required`)
    if (a?.releaseIdentity !== undefined && typeof a.releaseIdentity !== 'string') err(`artifacts[${i}].releaseIdentity must be a string`)
    const resolved = path.join(path.dirname(path.join(repoRoot, fileLabel)), a?.path ?? '')
    if (typeof a?.path === 'string' && !a.path.includes('..') && !existsSync(resolved) && a.path !== '.') {
      // relative artifact paths must exist beside the manifest unless virtual
      err(`artifacts[${i}].path does not exist beside the manifest: ${a.path}`)
    }
  }

  if (!Array.isArray(manifest.entries)) err('entries must be an array')
  else for (const [i, e] of manifest.entries.entries()) {
    if (typeof e?.entryId !== 'string' || e.entryId.length === 0) err(`entries[${i}].entryId is required`)
    if (typeof e?.entrypoint !== 'string' || e.entrypoint.length === 0) err(`entries[${i}].entrypoint is required`)
    if (!EXECUTION_DOMAINS.includes(e?.executionDomain)) err(`entries[${i}].executionDomain must be frontend|backend`)
    if (e?.existingRuntimeManifest !== undefined && typeof e.existingRuntimeManifest !== 'string') {
      err(`entries[${i}].existingRuntimeManifest must name the runtime manifest`)
    }
    for (const key of Object.keys(e ?? {})) {
      if (!['entryId', 'package', 'entrypoint', 'executionDomain', 'existingRuntimeManifest'].includes(key)) {
        err(`entries[${i}] has unknown key '${key}'`)
      }
    }
  }
  return errors
}

function discoverManifests(dir) {
  const found = []
  const stack = [dir]
  while (stack.length > 0) {
    const current = stack.pop()
    for (const name of readdirSync(current)) {
      if (['node_modules', 'dist', '.git', 'build'].includes(name)) continue
      const entry = path.join(current, name)
      const st = statSync(entry)
      if (st.isDirectory()) stack.push(entry)
      else if (name === 'plugin.manifest.json') found.push(entry)
    }
  }
  return found.sort()
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const roots = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['packages/frontend', 'packages/backend', 'plugins']
  const allErrors = []
  let count = 0
  for (const root of roots) {
    const abs = path.join(repoRoot, root)
    if (!existsSync(abs)) continue
    for (const file of discoverManifests(abs)) {
      count += 1
      const label = path.relative(repoRoot, file)
      try {
        const manifest = JSON.parse(readFileSync(file, 'utf8'))
        allErrors.push(...validateLogicalManifest(manifest, label))
      } catch (cause) {
        allErrors.push(`${label}: unreadable JSON: ${cause}`)
      }
    }
  }
  if (allErrors.length > 0) {
    console.error(allErrors.join('\n'))
    process.exit(1)
  }
  console.log(JSON.stringify({ kind: 'logical-manifest-validation', manifests: count, errors: 0, status: 'PASS' }))
}
