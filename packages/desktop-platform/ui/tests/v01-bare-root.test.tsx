// @vitest-environment jsdom
// V01 (C8 tasks matrix, positive half): every public foundation renders in a
// plain createRoot with no provider, no service, no registry mounted. The
// negative half (JS import creates no DOM/style/listener side effects) lives
// in v01-import-side-effects.test.tsx; this file additionally pins the module
// graph purity (no registry/app imports, no forbidden DOM escape hatches).
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  IconButton,
  Inline,
  Input,
  Notice,
  Panel,
  ScrollArea,
  Separator,
  Stack,
  Textarea,
  Select,
  Toolbar,
} from '../src/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** Locate this package's dir regardless of whether vitest runs from the repo
 * root (`--root packages/desktop-platform/ui`) or the package itself. */
function packageDir(): string {
  for (const start of [process.cwd(), resolve(process.cwd(), 'packages/desktop-platform/ui')]) {
    let dir = start
    for (let up = 0; up < 4; up++) {
      if (existsSync(resolve(dir, 'styles.css')) && existsSync(resolve(dir, 'src/index.ts'))) return dir
      dir = dirname(dir)
    }
  }
  throw new Error(`@ordessa/ui package dir not found from ${process.cwd()}`)
}

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})
async function mount(element: ReactNode): Promise<HTMLElement> {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => {
    await act(async () => root.unmount())
    container.remove()
  })
  await act(async () => root.render(element))
  return container
}

describe('V01 bare React root', () => {
  it('V01 every foundation renders in a bare createRoot with zero providers, services or registry mounted', async () => {
    const container = await mount(
      <Stack spacing="md" align="stretch" role="main">
        <Card.Root variant="subtle" padding="sm" aria-label="bare card">
          <Card.Header>
            <Card.Title>Title</Card.Title>
            <Card.Description>Description</Card.Description>
            <Card.Actions>
              <Button>Act</Button>
            </Card.Actions>
          </Card.Header>
          <Card.Body>Body</Card.Body>
          <Card.Footer>Footer</Card.Footer>
        </Card.Root>
        <Panel.Root aria-label="bare panel">
          <Panel.Header>
            <Panel.Title>Panel</Panel.Title>
            <Panel.Actions>
              <IconButton aria-label="close panel">✕</IconButton>
            </Panel.Actions>
          </Panel.Header>
          <Panel.Body>
            <ScrollArea direction="vertical">scroll content</ScrollArea>
          </Panel.Body>
          <Panel.Footer>foot</Panel.Footer>
        </Panel.Root>
        <Inline spacing="sm" wrap>
          <Separator />
          <Separator orientation="vertical" semantic />
        </Inline>
        <Toolbar aria-label="bare toolbar">
          <Button size="sm">A</Button>
          <Button busy>Busy</Button>
        </Toolbar>
        <Field.Root required>
          <Field.Label>Name</Field.Label>
          <Field.Control>{(a11y) => <Input {...a11y} value="" readOnly onChange={() => undefined} />}</Field.Control>
          <Field.Description>pick a name</Field.Description>
        </Field.Root>
        <Textarea defaultValue="t" />
        {/* A native select has no readOnly state, and SelectProps deliberately does not
            accept one: a consumer that means "cannot change it" uses disabled. */}
        <Select value="a" disabled onChange={() => undefined}>
          <option value="a">A</option>
        </Select>
        <Checkbox checked readOnly onChange={() => undefined} />
        <Badge tone="info">info</Badge>
        <Notice title="heads up">notice body</Notice>
        <EmptyState title="nothing here" description="later" />
      </Stack>,
    )
    for (const cls of [
      'ods-ui-stack', 'ods-ui-card', 'ods-ui-card-header', 'ods-ui-card-title', 'ods-ui-card-description',
      'ods-ui-card-actions', 'ods-ui-card-body', 'ods-ui-card-footer', 'ods-ui-panel', 'ods-ui-panel-header',
      'ods-ui-panel-title', 'ods-ui-panel-actions', 'ods-ui-panel-body', 'ods-ui-panel-footer', 'ods-ui-inline',
      'ods-ui-separator', 'ods-ui-toolbar', 'ods-ui-scroll-area', 'ods-ui-field', 'ods-ui-field-label',
      'ods-ui-field-control', 'ods-ui-field-description', 'ods-ui-button', 'ods-ui-icon-button', 'ods-ui-input',
      'ods-ui-textarea', 'ods-ui-select', 'ods-ui-checkbox', 'ods-ui-badge', 'ods-ui-notice', 'ods-ui-empty-state',
    ]) {
      expect(container.querySelectorAll(`.${cls}`).length, cls).toBeGreaterThanOrEqual(1)
    }
    expect(container.querySelector('.ods-ui-toolbar')?.getAttribute('role')).toBe('group')
    expect(container.querySelector('.ods-ui-card')?.getAttribute('aria-label')).toBe('bare card')
    // plain text content renders as DOM children, never as raw HTML injection
    expect(container.querySelector('.ods-ui-card-body')?.textContent).toBe('Body')
  })

  it('V01 counterexample: the module graph stays registry-free and side-effect-free at source level', () => {
    const srcDir = `${packageDir()}/src`
    const files = readdirSync(srcDir).filter(name => name.endsWith('.tsx') || name.endsWith('.ts'))
    expect(files.length).toBeGreaterThanOrEqual(5)
    const text = files.map(name => readFileSync(`${srcDir}/${name}`, 'utf8')).join('\n')
    // every import specifier is react or a sibling file — never the registry,
    // extension API, an app or a product module (C8 ruling 6)
    const specifiers = [...text.matchAll(/from\s+'([^']+)'/g)].map(m => m[1]!)
    expect(specifiers.length).toBeGreaterThan(0)
    for (const specifier of specifiers) {
      expect(specifier, specifier).toMatch(/^(react|\.\/)/)
    }
    // no escape hatches into the global environment or raw markup
    for (const forbidden of [
      '@ordessa/ui-components', '@ordessa/extension-api', '@extensions/',
      'dangerouslySetInnerHTML', 'addEventListener', 'localStorage', 'sessionStorage',
      'document.', 'window.', 'fetch(', 'setTimeout', 'setInterval', 'autoFocus', 'navigator.',
    ]) {
      expect(text, forbidden).not.toContain(forbidden)
    }
  })
})
