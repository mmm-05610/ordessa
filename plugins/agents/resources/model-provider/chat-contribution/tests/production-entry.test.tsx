import { expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

it('the shipped extension entry is the read-only selector and has no Agent config client path', () => {
  const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'))
  const build = readFileSync(new URL('../build.mjs', import.meta.url), 'utf8')
  const entry = readFileSync(new URL('../src/entry.tsx', import.meta.url), 'utf8')
  const selector = readFileSync(new URL('../src/canonical-selector.tsx', import.meta.url), 'utf8')
  expect(manifest.id).toBe('ordessa.model-provider-chat')
  expect(build).toContain('src/entry.tsx')
  expect(entry).toContain('canonicalModelSelectorComponent({ service })')
  expect(entry).not.toMatch(/AgentSessionsToken|WirePortToken|createWireConfigurationClient/)
  expect(selector).toContain('unsupportedEligibility')
  expect(selector).not.toMatch(/\.dispatch\(|\.prepare\(|\.forLocation\(|acpSessionId|agent\.config|profiles\.v2/)
})
