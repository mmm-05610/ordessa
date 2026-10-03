/**
 * T008-06 gates: connectors reach the native bridge only through the public
 * contract (`@ordessa/native-bridge`) — never `apps/desktop/**` internals —
 * and the API entry faces carry no Electron/React side effects (pure
 * declarations).
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const connectorsRoot = path.resolve(here, '..', '..') // plugins/connectors

function sourceFiles(dir: string): string[] {
  const found: string[] = []
  const stack = [dir]
  while (stack.length > 0) {
    const current = stack.pop()!
    for (const name of readdirSync(current)) {
      if (name === 'node_modules' || name === 'dist') continue
      const file = path.join(current, name)
      const st = statSync(file)
      if (st.isDirectory()) stack.push(file)
      else if (/\.[cm]?tsx?$/.test(name)) found.push(file)
    }
  }
  return found
}

describe('connectors stay on public contracts', () => {
  it('no connector source imports apps/desktop internals', () => {
    const violations: string[] = []
    for (const file of sourceFiles(connectorsRoot)) {
      if (file.includes('/tests/')) continue // tests may use fixtures
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(/(?:from|import|require\()\s*['"]([^'"]+)['"]/g)) {
        const specifier = match[1]
        if (specifier.includes('apps/desktop') || specifier.includes('apps/server')) {
          violations.push(`${path.relative(connectorsRoot, file)} -> ${specifier}`)
        }
      }
    }
    expect(violations).toEqual([])
  })

  it('api/entry faces carry no Electron/React side effects', () => {
    // The spec forbids Electron/React runtime imports and top-level exits;
    // window access is the renderer entry's legitimate job (T008-06 wording).
    const sideEffects = ['process.exit']
    const violations: string[] = []
    for (const connector of ['acp', 'ordessa']) {
      for (const face of ['api', 'src']) {
        const dir = path.join(connectorsRoot, connector, face)
        if (!existsSync(dir)) continue // acp has no api face; src alone is scanned
        for (const file of sourceFiles(dir)) {
          const source = readFileSync(file, 'utf8')
          for (const pattern of sideEffects) {
            // import statements are fine; top-level execution is not
            const lines = source.split('\n')
            for (const line of lines) {
              if (/^\s*(import|export)\b/.test(line)) continue
              if (line.includes(pattern) && !line.trimStart().startsWith('//')) {
                violations.push(`${path.relative(connectorsRoot, file)}: ${pattern}`)
              }
            }
          }
          if (/\bfrom\s+['"]react['"]|\bfrom\s+['"]electron['"]/.test(source)) {
            // type-only re-exports of public shapes are fine; runtime import is not
            for (const line of source.split('\n')) {
              if (/^\s*import\s+type\b/.test(line)) continue
              if (/\bfrom\s+['"](react|electron)['"]/.test(line)) {
                violations.push(`${path.relative(connectorsRoot, file)}: runtime ${line.trim()}`)
              }
            }
          }
        }
      }
    }
    expect(violations).toEqual([])
  })
})
