// @vitest-environment jsdom
// V03 component-level half (UIB003): Panel keeps header/footer fixed while the
// body owns scrolling; a ScrollArea inside it is the only scrollable child and
// long lines are bounded by the container contract, Card never collapses,
// drags, closes windows or hijacks scrolling, Toolbar keeps role="group" with
// native Tab order, and Separator distinguishes decorative from semantic.
// jsdom has no layout engine: these assert the DOM + styles.css contract, while
// the real 360px/768px geometry check in a browser is registered as main-agent
// work (UIB005/UIB007), NOT claimed as done here.
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { Button, Card, IconButton, Inline, Panel, ScrollArea, Separator, Stack, Toolbar } from '../src/index'

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

interface CssRule { selector: string; decls: string[] }
function parseRules(css: string): CssRule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const rules: CssRule[] = []
  let buf = ''
  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === '{') {
      const selector = buf.trim()
      let depth = 1
      let j = i + 1
      while (j < text.length && depth > 0) {
        if (text[j] === '{') depth++
        else if (text[j] === '}') depth--
        j++
      }
      const body = text.slice(i + 1, j - 1)
      if (selector.startsWith('@media')) rules.push(...parseRules(body))
      else if (selector.startsWith('@')) throw new Error(`unexpected at-rule ${selector}`)
      else rules.push({ selector, decls: body.split(';').map(d => d.trim()).filter(d => d.length > 0) })
      buf = ''
      i = j
      continue
    }
    buf += ch
    i++
  }
  return rules
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
const cssRules = parseRules(cssText)
function declsOf(selector: string): string[] {
  const rule = cssRules.find(r => r.selector === selector)
  expect(rule, `styles.css must define a rule for ${selector}`).toBeTruthy()
  return rule!.decls
}

describe('V03 containers and layout contract', () => {
  it('V03 Panel body is the element that owns scrolling and shrink control; header/footer never shrink', async () => {
    const bodyDecls = declsOf('.ods-ui-panel-body')
    expect(bodyDecls).toContain('min-height: 0')
    expect(bodyDecls).toContain('min-width: 0')
    expect(bodyDecls).toContain('flex: 1 1 auto')
    expect(bodyDecls).toContain('overflow: auto')
    expect(declsOf('.ods-ui-panel-header')).toContain('flex-shrink: 0')
    expect(declsOf('.ods-ui-panel-footer')).toContain('flex-shrink: 0')
    const container = await mount(
      <Panel.Root style={{ height: 200 }}>
        <Panel.Header><Panel.Title>Title</Panel.Title></Panel.Header>
        <Panel.Body>
          <ScrollArea direction="vertical" aria-label="long lines">
            <p>{'x'.repeat(5000)}</p>
          </ScrollArea>
        </Panel.Body>
        <Panel.Footer>foot</Panel.Footer>
      </Panel.Root>,
    )
    const panel = container.querySelector('.ods-ui-panel')!
    expect([...panel.children].map(n => n.className.split(' ')[0]))
      .toEqual(['ods-ui-panel-header', 'ods-ui-panel-body', 'ods-ui-panel-footer'])
    // the long line only sits inside the designated scroll owners: body and the
    // ScrollArea within it — no other ancestor carries an overflow property
    const scroll = container.querySelector('.ods-ui-scroll-area')!
    expect(panel.contains(scroll)).toBe(true)
    expect(scroll.className).toContain('ods-ui-scroll-area--vertical')
    for (const outer of [panel, container.firstElementChild!.parentElement!]) {
      expect(outer.className).not.toContain('ods-ui-scroll-area')
    }
    // ScrollArea bounds any line: max-width:100% + min-width:0 keep the outer
    // element from being forced wider than its container
    const areaDecls = cssRules.filter(r => r.selector.includes('.ods-ui-scroll-area')).flatMap(r => r.decls)
    expect(areaDecls).toContain('max-width: 100%')
    expect(areaDecls).toContain('min-width: 0')
    expect(areaDecls).toContain('overscroll-behavior: contain')
    expect(areaDecls).not.toContain('scroll-behavior: smooth')
  })

  it('V03 counterexample: Card is a plain box — no collapse affordance, no drag, no window or scroll hijack', async () => {
    const container = await mount(
      <Card.Root variant="outlined" padding="md" aria-label="static card">
        <Card.Header><Card.Title>T</Card.Title></Card.Header>
        <Card.Body>content</Card.Body>
      </Card.Root>,
    )
    const card = container.querySelector('.ods-ui-card') as HTMLElement
    expect(card.tagName).toBe('DIV')
    expect(card.getAttribute('aria-label')).toBe('static card')
    // no auto-collapse: no disclosure state, no toggle control appears by itself
    expect(card.hasAttribute('aria-expanded')).toBe(false)
    expect(container.querySelectorAll('button')).toHaveLength(0)
    // no drag, no window semantics
    expect(card.draggable).toBe(false)
    expect(card.hasAttribute('role')).toBe(false)
    // no scrolling owned or hijacked by the Card itself
    for (const rule of cssRules.filter(r => r.selector.includes('.ods-ui-card'))) {
      for (const decl of rule.decls) {
        expect(decl, `${rule.selector}: ${decl}`).not.toMatch(/^(overflow|overflow-[xy]|scroll-behavior|position):/)
      }
    }
    // consumer-provided actions still work: a Card with an IconButton renders
    // exactly what children put in — no more
    const second = await mount(
      <Card.Root>
        <Card.Header>
          <Card.Title>T</Card.Title>
          <Card.Actions><IconButton aria-label="archive">A</IconButton></Card.Actions>
        </Card.Header>
      </Card.Root>,
    )
    expect(second.querySelectorAll('button')).toHaveLength(1)
    expect(second.querySelector('button')!.getAttribute('aria-label')).toBe('archive')
  })

  it('V03 Toolbar keeps role="group", its accessible name, native Tab order and no key hijacking', async () => {
    const container = await mount(
      <Toolbar aria-label="Editor actions" orientation="vertical">
        <Button>One</Button>
        <Button>Two</Button>
      </Toolbar>,
    )
    const toolbar = container.querySelector('.ods-ui-toolbar')!
    expect(toolbar.getAttribute('role')).toBe('group')
    expect(toolbar.getAttribute('aria-label')).toBe('Editor actions')
    expect(toolbar.className).toContain('ods-ui-toolbar--vertical')
    // v1 = native Tab order: no roving tabindex or aria-orientation toolbar
    // semantics are claimed
    for (const node of toolbar.querySelectorAll('*')) {
      expect(node.hasAttribute('tabindex'), `${node.nodeName} got a tabindex`).toBe(false)
    }
    expect(toolbar.hasAttribute('aria-orientation')).toBe(false)
    // a Tab keydown is never swallowed by the foundations
    const first = toolbar.querySelectorAll('button')[0]!
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    await act(async () => { first.dispatchEvent(event) })
    expect(event.defaultPrevented, 'foundations must not preventDefault Tab').toBe(false)
    // native focus order follows DOM order: focus the second button directly
    const second = toolbar.querySelectorAll('button')[1] as HTMLButtonElement
    await act(async () => { second.focus() })
    expect(document.activeElement).toBe(second)
  })

  it('V03 ScrollArea forwards the ref and takes the direction, Stack/Inline map tokens to classes', async () => {
    const areaRef: { current: HTMLDivElement | null } = { current: null }
    const container = await mount(
      <>
        <ScrollArea ref={areaRef} direction="horizontal" />
        <Stack spacing="lg" align="center" justify="between" />
        <Inline spacing="xs" wrap />
      </>,
    )
    expect(areaRef.current).toBeInstanceOf(HTMLDivElement)
    expect(areaRef.current!.className).toContain('ods-ui-scroll-area--horizontal')
    const stack = container.querySelectorAll('.ods-ui-stack')[0]!
    expect(stack.classList.contains('ods-ui-stack--gap-lg')).toBe(true)
    expect(stack.classList.contains('ods-ui-stack--align-center')).toBe(true)
    expect(stack.classList.contains('ods-ui-stack--justify-between')).toBe(true)
    const inline = container.querySelector('.ods-ui-inline')!
    expect(inline.classList.contains('ods-ui-inline--gap-xs')).toBe(true)
    expect(inline.classList.contains('ods-ui-inline--wrap')).toBe(true)
  })

  it('V03 Separator is decorative by default and semantic only when asked', async () => {
    const container = await mount(
      <>
        <Separator />
        <Separator semantic orientation="vertical" />
      </>,
    )
    const [plain, semantic] = container.querySelectorAll('.ods-ui-separator')
    expect(plain!.getAttribute('aria-hidden')).toBe('true')
    expect(plain!.hasAttribute('role')).toBe(false)
    expect(semantic!.getAttribute('role')).toBe('separator')
    expect(semantic!.getAttribute('aria-orientation')).toBe('vertical')
    expect(semantic!.hasAttribute('aria-hidden')).toBe(false)
  })
})
