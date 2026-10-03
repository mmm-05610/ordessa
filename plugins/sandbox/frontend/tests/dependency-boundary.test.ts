// Independence gate (verification.md extra-gate 2 / FR-08): the Sandbox domain
// installs and works with no Permissions domain present, and it reaches the
// platform only through published contract surfaces. This guards the import
// graph itself rather than trusting a review comment.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcDir = fileURLToPath(new URL('../src', import.meta.url))
const sources: string[] = []
for (const entry of readdirSync(srcDir, { withFileTypes: true })) {
  if (entry.isDirectory()) for (const f of readdirSync(`${srcDir}/${entry.name}`)) sources.push(`${srcDir}/${entry.name}/${f}`)
  else sources.push(`${srcDir}/${entry.name}`)
}
const moduleFiles = sources.filter(f => /\.tsx?$/.test(f))
function specifiers(file: string): string[] {
  const text = readFileSync(file, 'utf8')
  return [...text.matchAll(/(?:^|\n)\s*(?:import|export)[\s\S]*?from\s+['"]([^'"]+)['"]/g)].map(m => m[1])
}

describe('sandbox settings domain boundary', () => {
  it('has source files to guard', () => {
    expect(moduleFiles.length).toBeGreaterThanOrEqual(3)
  })

  it('imports nothing from the Permissions domain', () => {
    for (const file of moduleFiles) {
      const offending = specifiers(file).filter(s => /permission/i.test(s))
      expect(offending, `${file} must not depend on Permissions`).toEqual([])
    }
    const joined = moduleFiles.map(f => readFileSync(f, 'utf8')).join('\n')
    expect(joined).not.toMatch(/ordessa_permissions|permissions\.authorizer|permissions\/frontend/)
  })

  it('reaches the platform only through published contract / UI packages', () => {
    const allowed = new Set([
      'react', 'react-dom',
      '@ordessa/extension-api',
      '@extensions/ordessa.contracts/contract.js',
      '@ordessa/ui',
    ])
    for (const file of moduleFiles) {
      for (const specifier of specifiers(file)) {
        if (specifier.startsWith('.')) continue
        expect(allowed.has(specifier), `${file} imports non-public ${specifier}`).toBe(true)
      }
    }
  })

  it('never reaches into host or workbench internals', () => {
    for (const file of moduleFiles) {
      const offenders = specifiers(file).filter(s => /extension-host|workbench\/src|desktop-platform\/.*\/src/.test(s))
      expect(offenders, `${file} must use the contract, not internals`).toEqual([])
    }
  })
})
