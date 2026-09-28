// @vitest-environment jsdom
// V04 component-level half (styles contract of UIB002–UIB004): every rule in
// styles.css is scoped to `.ods-ui-*` classes this package owns; no bare
// element selectors, no `:root`, no universal selector, no `!important`, no
// global reset; theme variables are consumed with a local fallback and never
// redefined; reduced motion is honoured. Anything outside the foundation tree
// provably keeps its own DOM and class list. Real computed-style checks against
// the Workbench stylesheet in a browser remain main-agent work (UIB005).
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { Badge, Button, Card, Field, Input, Panel, Stack } from '../src/index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
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
const cssText = readFileSync(resolve(packageDir(), 'styles.css'), 'utf8')

const BARE_ELEMENTS =
  'a|abbr|address|area|article|aside|audio|b|body|button|canvas|caption|code|col|data|datalist|dd|del|details|dfn|dialog|div|dl|dt|em|embed|fieldset|figcaption|figure|footer|form|h1|h2|h3|h4|h5|h6|header|hgroup|hr|html|i|iframe|img|input|ins|kbd|label|legend|li|link|main|map|mark|menu|meta|meter|nav|noscript|object|ol|optgroup|option|output|p|picture|pre|progress|q|rp|rt|ruby|s|samp|script|search|section|select|slot|small|source|span|strong|style|sub|summary|sup|table|tbody|td|template|textarea|tfoot|th|thead|time|title|tr|track|u|ul|var|video|wbr'

function* eachSelector(text: string): Generator<string> {
  // Every `{`-introducing prelude, comments stripped. Declarations are excluded
  // from preludes because no selector in this file may contain `;`, `{` or `}`;
  // at-rule preludes (which start with `@`) are skipped — their inner rules are
  // yielded separately.
  const stripped = text.replace(/\/\*[\s\S]*?\*\//g, '')
  for (const match of stripped.matchAll(/([^{};]+)\{/g)) {
    const prelude = match[1]!.trim()
    if (prelude.startsWith('@')) continue
    for (const sel of prelude.split(',')) yield sel.trim()
  }
}

describe('V04 style scoping contract', () => {
  it('V04 every selector is scoped to .ods-ui-* — no bare elements, no :root, no universal reset, no attribute-globals', () => {
    expect(cssText.length).toBeGreaterThan(1000)
    const selectors = [...eachSelector(cssText)]
    expect(selectors.length).toBeGreaterThan(50)
    for (const sel of selectors) {
      if (sel.startsWith('@media')) continue
      expect(sel, `selector "${sel}" must carry the .ods-ui- prefix`).toContain('.ods-ui-')
      expect(sel, `selector "${sel}" must not target :root`).not.toContain(':root')
      expect(sel, `selector "${sel}" must not use a universal selector`).not.toContain('*')
      expect(
        sel,
        `selector "${sel}" must not select a bare element name`,
      ).not.toMatch(new RegExp(`(^|[\\s>+~(])(${BARE_ELEMENTS})(\\s|$|[.\\[:>#])`))
    }
  })

  it('V04 the stylesheet contains no !important, no position fixed/sticky, and never redefines host theme variables', () => {
    // scan the executable CSS only — comments may name the bans they document
    const cssCode = cssText.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(cssCode).not.toContain('!important')
    expect(cssCode).not.toMatch(/position:\s*(fixed|sticky)/)
    // `--ui-*` may appear inside var(...) with a fallback, but a declaration
    // like `--ui-surface: ...` (with or without a leading space before `:`)
    // would override the host theme — banned outright.
    expect(cssCode).not.toMatch(/--ui-[a-z0-9-]+\s*:/)
    // same for the html/body roots of the host
    expect(cssCode).not.toMatch(/(^|\})\s*(html|body)[\s,.:{]/)
  })

  it('V04 every theme-variable consumption carries a local fallback so a bare React root still looks right', () => {
    const bareUses = cssText.match(/var\(--ui-[a-z0-9-]+\)/g) ?? []
    expect(bareUses, `var(--ui-*) without fallback: ${bareUses.join(', ')}`).toEqual([])
    const withFallback = cssText.match(/var\(--ui-[a-z0-9-]+,\s*[^)]+\)/g) ?? []
    expect(withFallback.length).toBeGreaterThan(20)
    // the fallbacks use the Workbench host's real variable names
    for (const name of ['--ui-surface', '--ui-ink', '--ui-line', '--ui-accent', '--ui-error', '--ui-ok', '--ui-warn', '--ui-ink-secondary', '--ui-ink-faint', '--ui-sunken', '--ui-hover', '--ui-nav']) {
      expect(cssText, `${name} must be consumed`).toContain(`var(${name},`)
    }
  })

  it('V04 reduced motion is honoured: a prefers-reduced-motion block disables the transitions', () => {
    expect(cssText).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
    const block = cssText.slice(cssText.indexOf('prefers-reduced-motion'))
    expect(block).toContain('transition: none')
    // and the reduced-motion block is itself .ods-ui-scoped
    expect(block.slice(block.indexOf('{'))).toContain('.ods-ui-')
    // base rules do animate (otherwise the reduced-motion block would be moot)
    expect(cssText).toContain('transition: background-color')
  })

  it('V04 counterexample: non-foundations DOM keeps its own classes untouched by import and render', async () => {
    const legacy = document.createElement('div')
    legacy.className = 'legacy-app'
    legacy.innerHTML = '<button class="legacy-btn">legacy</button><p class="legacy-para">text</p>'
    document.body.append(legacy)
    cleanups.push(async () => legacy.remove())
    const snapshot = legacy.innerHTML
    await mount(
      <Stack spacing="sm">
        <Card.Root><Card.Body>x</Card.Body></Card.Root>
        <Panel.Root><Panel.Body>y</Panel.Body></Panel.Root>
        <Button>B</Button>
        <Field.Root>
          <Field.Label>L</Field.Label>
          <Field.Control>{(a11y) => <Input {...a11y} value="" readOnly onChange={() => undefined} />}</Field.Control>
        </Field.Root>
        <Badge tone="neutral">n</Badge>
      </Stack>,
    )
    expect(legacy.innerHTML, 'foundations must not touch foreign DOM').toBe(snapshot)
    expect(legacy.querySelector('.legacy-btn')!.className).toBe('legacy-btn')
    expect(legacy.querySelector('.legacy-btn')!.getAttribute('style')).toBe(null)
    // and the package never injected a stylesheet by itself
    expect(document.querySelectorAll('style').length).toBe(0)
  })
})
