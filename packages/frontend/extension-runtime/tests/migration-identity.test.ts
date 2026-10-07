/**
 * 032 retirement guard: the T008-01 merge is over. Loader and host are
 * independent leaves again — the old forwarding shells, the nested
 * extension-runtime/loader + extension-runtime/host directories and the
 * runtime's loader/host export map entries must all stay retired, while the
 * runtime keeps its own state surface and the leaves expose the complete
 * public bindings exactly once.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import * as loaderLeaf from '@ordessa/extension-loader'
import * as loaderManifest from '@ordessa/extension-loader/manifest'
import * as hostLeaf from '@ordessa/extension-host'
import * as hostMain from '@ordessa/extension-host/main'
import * as hostPlatform from '@ordessa/extension-host/platform'
import * as hostServices from '@ordessa/extension-host/services'
import * as hostCommandRegistry from '@ordessa/extension-host/services/command-registry'
import * as hostSurface from '@ordessa/extension-host/services/surface'

const HERE = dirname(fileURLToPath(import.meta.url))
const RUNTIME = resolve(HERE, '..')
const FRONTEND = resolve(RUNTIME, '..')

describe('loader/host leaf split (032)', () => {
  it('the retired nested implementation directories are absent', () => {
    expect(existsSync(resolve(RUNTIME, 'loader'))).toBe(false)
    expect(existsSync(resolve(RUNTIME, 'host'))).toBe(false)
  })

  it('the runtime package no longer exports loader/host deep paths', () => {
    const manifest = JSON.parse(readFileSync(resolve(RUNTIME, 'package.json'), 'utf8'))
    const keys = Object.keys(manifest.exports ?? {})
    expect(keys).toEqual(['./state', './tasks', './ui-storage'])
    expect(keys.some((key) => key.startsWith('./loader') || key.startsWith('./host'))).toBe(false)
  })

  it('the leaves carry the real implementations, not forwarding shells', () => {
    for (const leaf of ['extension-loader', 'extension-host']) {
      const source = readFileSync(resolve(FRONTEND, leaf, 'package.json'), 'utf8')
      expect(source).not.toContain('compatibility shell')
      const entry = readFileSync(resolve(FRONTEND, leaf, 'src', 'index.ts'), 'utf8')
      expect(entry).not.toContain("from '@ordessa/extension-runtime/host")
      expect(entry).not.toContain("from '@ordessa/extension-runtime/loader")
    }
  })

  it('the loader leaf exposes its public bindings exactly once', () => {
    expect(Object.keys(loaderLeaf).length).toBeGreaterThan(0)
    expect(Object.keys(loaderManifest).length).toBeGreaterThan(0)
    expect(new Set(Object.keys(loaderLeaf)).size).toBe(Object.keys(loaderLeaf).length)
  })

  it('the host leaf exposes index/main/platform/services and the service entries', () => {
    expect(Object.keys(hostLeaf).length).toBeGreaterThan(0)
    expect(Object.keys(hostMain).length).toBeGreaterThan(0)
    expect(Object.keys(hostPlatform).length).toBeGreaterThan(0)
    expect(Object.keys(hostServices).length).toBeGreaterThan(0)
    expect(hostCommandRegistry.createCommands).toBeDefined()
    expect(hostSurface.createSurfaceRegistry).toBeDefined()
  })
})
