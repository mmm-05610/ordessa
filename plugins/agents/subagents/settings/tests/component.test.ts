/**
 * The React renderer, exercised with `react-dom/server` (no browser, no jsdom):
 * the markup really produced from the model, checked for the safety and
 * truthfulness properties the task claims — and nothing beyond them.
 */
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { createSettingsComponent } from '../src/component'
import { createSettingsStore } from '../src/store'
import { initialState, reduce, type SettingsState } from '../src/model'
import { SETTINGS_SECTION_ID, createSettingsSection } from '../src/section'
import { detailOf, OTHER_TARGET, summaryOf, TARGET } from './fixtures'

function render(state: SettingsState): string {
  const store = createSettingsStore({ port: null, target: state.target, viewerPrincipal: 'principal-1' })
  store.dispatch({ type: 'target/switch', target: state.target })
  // drive the store to the state under test, then render it
  for (const action of stateActions(state)) store.dispatch(action)
  void reduce
  const section = createSettingsSection({ store })
  expect(section.id).toBe(SETTINGS_SECTION_ID)
  return renderToStaticMarkup(createElement(section.component, {}))
}

/** Rebuild a state through the reducer so the rendered markup is the real flow. */
function stateActions(state: SettingsState) {
  return [
    { type: 'list/result' as const, stamp: state.target, result: { ok: true as const, stamp: state.target, data: state.list.data ?? [] } },
    ...(state.selection === null ? [] : [{ type: 'detail/select' as const, definitionId: state.selection }]),
    ...(state.detail.data === null ? [] : [{ type: 'detail/result' as const, definitionId: state.detail.data.definitionId, stamp: state.target, result: { ok: true as const, stamp: state.target, data: state.detail.data } }]),
    ...(state.native.data ? [{ type: 'native/result' as const, stamp: state.target, result: { ok: true as const, stamp: state.target, data: state.native.data } }] : []),
    // Replay the open dialog too, so dialog assertions exercise the real reduce →
    // view → React flow instead of a state the driver never rebuilds.
    ...(state.dialog.kind === 'none' ? [] : [{ type: 'dialog/open' as const, dialog: state.dialog }]),
  ]
}

function detailState(target = TARGET): SettingsState {
  const base = initialState({ target, viewerPrincipal: 'principal-1', serviceAvailable: true })
  const withRows = reduce(base, { type: 'list/result', stamp: target, result: { ok: true, stamp: target, data: [detailOf()] } })
  const selected = reduce(withRows, { type: 'detail/select', definitionId: 'def-1' })
  const requested = reduce(selected, { type: 'detail/request', definitionId: 'def-1' })
  return reduce(requested, { type: 'detail/result', definitionId: 'def-1', stamp: target, result: { ok: true, stamp: target, data: detailOf() } })
}

describe('rendered markup', () => {
  it('produces real elements with the aria/data attributes the model declared', () => {
    const html = render(detailState())
    expect(html).toContain('role="listbox"')
    expect(html).toContain('role="option"')
    expect(html).toContain('aria-label="查看 只读代码审阅者"')
    expect(html).toContain('data-facet="assets.native-subagents"')
    expect(html).toContain('target修订'.replace('target', '目标'))
  })

  it('never emits raw HTML, an image, or an executable attribute', () => {
    const state = detailState()
    const withHostile = reduce(state, {
      type: 'detail/result', definitionId: 'def-1', stamp: TARGET,
      result: {
        ok: true, stamp: TARGET,
        data: detailOf({
          latestContent: { ...detailOf().latestContent!, roleBody: '<img src=x onerror=alert(1)> [x](javascript:alert(1)) token=sk-abcdefghijklmnop1234' },
        }),
      },
    })
    const html = render(withHostile)
    expect(html).not.toContain('<img')
    expect(html).not.toMatch(/onerror=/i)
    expect(html).not.toMatch(/<script/i)
    expect(html.toLowerCase()).not.toContain('href="javascript:')
    expect(html).not.toContain('sk-abcdefghijklmnop1234')
    // the hostile source is still *shown* to the reader, as escaped text
    expect(html).toContain('&lt;img')
  })

  it('a stored-only row never renders as an applied state', () => {
    const html = render(detailState())
    expect(html).not.toContain('已生效')
    expect(html).toContain('未应用')
    expect(html).toContain('data-badge="stored-only"')
  })

  it('an unverified fact renders without a check or a cross', () => {
    const html = render(detailState())
    expect(html).toContain('data-tone="unknown"')
    expect(html).toContain('装载未验证')
    // the glyph attribute is empty for unknown, and no ✓/✗ sits next to it
    expect(html).toMatch(/data-fact="loaded"[^>]*data-glyph=""/)
  })

  it('the diff dialog renders inside the section, so tab reaches it', () => {
    const opened = reduce(detailState(), {
      type: 'dialog/open',
      dialog: { kind: 'revision-diff', definitionId: 'def-1', from: 1, to: 2, lines: [{ kind: 'added', text: '输出差异清单。' }] },
    })
    const html = render(opened)
    expect(html).toContain('data-dialog="revision-diff"')
    expect(html).toContain('返回列表')
    expect(html).toContain('输出差异清单。')
  })

  it('the service-absent render explains itself instead of spinning or crashing', () => {
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    store.reload()
    const section = createSettingsSection({ store })
    const html = renderToStaticMarkup(createElement(section.component, {}))
    expect(html).toContain('data-state="absent"')
    expect(html).toContain('C0 foundation')
    expect(html).not.toContain('aria-busy')
    expect(html).not.toMatch(/plugin failed|插件故障/)
  })

  it('a late response from another target leaves the rendered rows unchanged', async () => {
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    const component = createSettingsComponent(store)
    const before = renderToStaticMarkup(createElement(component, {}))
    store.dispatch({ type: 'list/result', stamp: OTHER_TARGET, result: { ok: true, stamp: OTHER_TARGET, data: [summaryOf({ definitionId: 'def-foreign' })] } })
    const after = renderToStaticMarkup(createElement(component, {}))
    expect(after).toBe(before)
    expect(after).not.toContain('def-foreign')
  })
})
