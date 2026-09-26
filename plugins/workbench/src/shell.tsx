import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Group, Panel, Separator, type PanelImperativeHandle } from 'react-resizable-panels'
import type { Commands, Region, UIContribution, View, WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import { ordered } from '../shared/registry'
import { Boundary } from '../shared/boundary'
import { placePopover } from './popover'
import { SETTINGS_OVERLAY_ID, type OverlayInstance, type WorkbenchModel } from './model'
import { styles } from './styles'

const regions: Region[] = ['left', 'main', 'right', 'top', 'bottom']
const auxiliary = ['left', 'right', 'bottom', 'top'] as const
const labels: Record<Region, string> = { left: '左侧栏', right: '右侧栏', bottom: '底部面板', top: '顶部面板', main: '主区' }
type Hosts = Partial<Record<Region, HTMLDivElement | null>>
// A stable portal container moves between slots, preserving the component instance.
function ViewSurface({ view, region, hosts }: { view: View; region: Region; hosts: RefObject<Hosts> }) {
  const [node] = useState(() => { const el = document.createElement('div'); el.className = 'wb-surface'; return el })
  useLayoutEffect(() => { hosts.current[region]?.appendChild(node); return () => { node.remove() } }, [region, node, hosts])
  const Content = view.component
  return createPortal(<Boundary><Content /></Boundary>, node)
}
function RegionIcon({ region }: { region: Region }) {
  return <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><rect x="2" y="3" width="16" height="14" rx="1" />
    {region === 'left' ? <path d="M7 3v14" /> : region === 'right' ? <path d="M13 3v14" /> : region === 'bottom' ? <path d="M2 12h16" /> : <path d="M2 8h16" />}</svg>
}

// Modal surfaces wrap Tab at their edges: focus cycles inside the surface and
// never reaches the inert background behind the overlay.
const trapTab = (surface: RefObject<HTMLElement | null>) => (event: { key: string; shiftKey: boolean; preventDefault(): void }) => {
  if (event.key !== 'Tab' || !surface.current) return
  const node = surface.current
  const items = [...node.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
  if (!items.length) return
  const edge = event.shiftKey ? items[0] : items[items.length - 1], wrap = event.shiftKey ? items[items.length - 1] : items[0]
  if (document.activeElement !== edge && node.contains(document.activeElement)) return
  event.preventDefault()
  wrap.focus()
}

// Overlays share one stack and one mount container: each instance captures the
// focus on mount and restores it to a connected safe target on unmount.
function useOverlayFocus(surface: RefObject<HTMLDivElement | null>, workspace: RefObject<HTMLDivElement | null>) {
  const restore = useRef<HTMLElement | null>(null)
  useLayoutEffect(() => {
    restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    surface.current?.focus()
    return () => {
      const target = restore.current
      queueMicrotask(() => {
        if (target?.isConnected && !target.closest('[inert]')) target.focus()
        else workspace.current?.focus()
      })
    }
  }, [])
}

function OverlaySurface({ entry, title, presentation, inert, close, workspace, children }: {
  entry: OverlayInstance; title: string; presentation: 'popover' | 'dialog' | 'page'; inert: boolean
  close(): void; workspace: RefObject<HTMLDivElement | null>; children: ReactNode
}) {
  const surface = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
  useOverlayFocus(surface, workspace)
  const anchor = entry.anchor
  const closeRef = useRef(close); closeRef.current = close
  useEffect(() => {
    if (presentation !== 'popover' || !anchor) return
    // A popover whose anchor left the DOM closes explicitly instead of lingering detached.
    const observer = new MutationObserver(() => { if (!anchor.isConnected) closeRef.current() })
    observer.observe(document, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [presentation, anchor])
  useLayoutEffect(() => {
    if (presentation !== 'popover' || !anchor) return
    const update = () => {
      const size = surface.current?.getBoundingClientRect()
      setPosition(placePopover(anchor.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }, { width: size?.width ?? 0, height: size?.height ?? 0 }))
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [presentation, anchor])
  const modal = presentation !== 'popover'
  return <div className={`wb-overlay wb-overlay-${presentation}`} data-overlay-id={entry.overlayId} data-presentation={presentation}
    style={presentation === 'popover' && position ? { left: position.left, top: position.top } : undefined} inert={inert}>
    <div ref={surface} tabIndex={-1} className="wb-overlay-surface" role="dialog" aria-label={title} aria-modal={modal || undefined} onKeyDown={modal ? trapTab(surface) : undefined}>
      <header className="wb-overlay-bar"><strong>{title}</strong><button aria-label={`关闭${title}`} onClick={close}>×</button></header>
      <div className="wb-overlay-content"><Boundary>{children}</Boundary></div>
    </div>
  </div>
}

function SettingsOverlay({ entry, sections, inert, close, workspace }: {
  entry: OverlayInstance; sections: readonly WorkbenchSettingsSection[]; inert: boolean
  close(): void; workspace: RefObject<HTMLDivElement | null>
}) {
  const surface = useRef<HTMLDivElement>(null)
  useOverlayFocus(surface, workspace)
  useLayoutEffect(() => {
    if (!entry.sectionId || !surface.current) return
    const target = [...surface.current.querySelectorAll<HTMLElement>('[data-section-id]')].find(node => node.dataset.sectionId === entry.sectionId)
    target?.scrollIntoView?.({ block: 'start' })
  }, [entry.sectionId, sections])
  return <div className="wb-overlay wb-overlay-page" data-overlay-id={SETTINGS_OVERLAY_ID} data-presentation="page" inert={inert}>
    <div ref={surface} tabIndex={-1} className="wb-overlay-surface wb-settings" role="dialog" aria-label="设置" aria-modal="true" onKeyDown={trapTab(surface)}>
      <header className="wb-overlay-bar"><strong>设置</strong><button aria-label="关闭设置" onClick={close}>×</button></header>
      <div className="wb-overlay-content">
        {ordered(sections).map(section => {
          const Content = section.component
          return <section key={section.id} className="wb-settings-section" data-section-id={section.id} data-active-section={entry.sectionId === section.id || undefined}>
            <h2>{section.title}</h2><Boundary><Content /></Boundary>
          </section>
        })}
        {!sections.length && <p className="wb-settings-empty">没有已注册的设置分区。</p>}
      </div>
    </div>
  </div>
}

export function WorkbenchShell({ model, commands }: { model: WorkbenchModel; commands: Commands }) {
  const views = useSyncExternalStore(model.views.subscribe, model.views.getSnapshot)
  const items = useSyncExternalStore(model.ui.subscribe, model.ui.getSnapshot)
  const selection = useSyncExternalStore(model.subscribe, model.getSelection)
  const layout = useSyncExternalStore(model.subscribe, model.getLayout)
  const available = useSyncExternalStore(commands.subscribe, commands.getSnapshot)
  const modules = useSyncExternalStore(model.modules.subscribe, model.modules.getSnapshot)
  const overlayDefs = useSyncExternalStore(model.overlays.subscribe, model.overlays.getSnapshot)
  const sections = useSyncExternalStore(model.sections.subscribe, model.sections.getSnapshot)
  const overlayStack = useSyncExternalStore(model.subscribe, model.getOverlayStack)
  const [error, setError] = useState(''), [dragged, setDragged] = useState<string | null>(null)
  const dragSession = useRef<string | null>(null)
  const full = views.find(v => v.id === selection['full-page'])
  const back = useRef<HTMLButtonElement>(null), workspace = useRef<HTMLDivElement>(null)
  const restore = useRef<HTMLElement | null>(null), hosts = useRef<Hosts>({})
  const panels = useRef<Partial<Record<Region, PanelImperativeHandle | null>>>({})
  const sizes = useRef<Partial<Record<Region, number>>>({ left: 22, right: 22, top: 18, bottom: 24 })
  const entries = (region: Region) => ordered(views.filter(v => model.regionOf(v) === region))
  const has = Object.fromEntries(regions.map(r => [r, entries(r).length > 0])) as Record<Region, boolean>
  const presentationOf = (entry: OverlayInstance): 'popover' | 'dialog' | 'page' =>
    entry.overlayId === SETTINGS_OVERLAY_ID ? 'page' : overlayDefs.find(o => o.id === entry.overlayId)?.presentation ?? 'dialog'
  const hasModal = overlayStack.some(entry => presentationOf(entry) !== 'popover')
  useLayoutEffect(() => {
    for (const r of auxiliary) {
      const panel = panels.current[r]
      if (!panel) continue
      if (!has[r] || layout.collapsed[r]) panel.collapse()
      else if (panel.isCollapsed()) panel.resize(`${sizes.current[r]}%`)
    }
  }, [layout.collapsed, has.left, has.right, has.top, has.bottom])
  useLayoutEffect(() => {
    if (!full) return
    restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    back.current?.focus()
    return () => {
      const target = restore.current
      queueMicrotask(() => {
        if (target?.isConnected && !target.closest('[inert]')) target.focus()
        else workspace.current?.focus()
      })
    }
  }, [full?.id])
  useEffect(() => {
    if (!overlayStack.length) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      model.closeTopOverlay()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [overlayStack.length, model])
  const activate = (id: string) => { setError(''); try { model.composition.activateModule(id) } catch (e) { setError(String(e)) } }
  const openSettings = () => { setError(''); try { model.composition.openSettings() } catch (e) { setError(String(e)) } }
  const contribution = (item: UIContribution) => {
    if (item.kind === 'component') { const Content = item.component; return <Boundary key={item.id}><Content /></Boundary> }
    const command = available.find(c => c.id === item.command), title = item.label ?? command?.title ?? item.command
    const Icon = item.icon
    return <button key={item.id} disabled={!command} aria-label={title} title={command ? title : `命令不可用：${item.command}`}
      onClick={() => { setError(''); void commands.execute(item.command).then(result => { if (!result.ok) setError(result.error) }) }}>
      {item.slot === 'navigation' && <span className="wb-nav-icon" aria-hidden="true">{Icon ? <Icon /> : title.slice(0, 1)}</span>}
      <span>{title}{!command && '（不可用）'}</span>
    </button>
  }
  const slot = (name: UIContribution['slot'], section?: 'primary' | 'utility') => ordered(items.filter(i => i.slot === name && (!section || (i.kind === 'command' && (i.section ?? 'primary') === section)))).map(contribution)
  const move = (id: string, region: Region) => { try { model.move(id, region) } catch (e) { setError(String(e)) } finally { setDragged(null) } }
  const navItems = slot('navigation', 'primary')
  const moduleNav = ordered(modules).map(m => {
    const Icon = m.icon
    return <button key={m.id} data-module-nav={m.id} aria-label={m.title} aria-pressed={selection.main === m.homeViewId} title={m.title} onClick={() => activate(m.id)}>
      <span className="wb-nav-icon" aria-hidden="true">{Icon ? <Icon /> : m.title.slice(0, 1)}</span><span>{m.title}</span>
    </button>
  })
  const region = (name: Region) => {
    const list = entries(name), active = list.find(v => v.id === selection[name])
    // A tab strip is worth showing only for two or more views; a single view
    // renders bare and keeps its move/close controls in wb-region-actions.
    return <section className={`wb-region wb-${name}`} data-region={name} aria-label={labels[name]} inert={name !== 'main' && (!has[name] || !!layout.collapsed[name])}>
      <header>{name === 'left' && <strong className="wb-brand">Ordessa</strong>}
        {list.length >= 2 && <div role="group" aria-label={`${name}视图`}>{list.map(v => <button key={v.id} draggable aria-pressed={v.id === active?.id}
          onDragStart={e => {
            e.dataTransfer.setData('application/x-ordessa-view', v.id); e.dataTransfer.setData('text/plain', v.title); e.dataTransfer.effectAllowed = 'move'
            dragSession.current = v.id
            // Let Chromium capture its drag image before adding an overlay over the source.
            setTimeout(() => { if (dragSession.current === v.id) setDragged(v.id) }, 0)
          }}
          onDragEnd={() => { dragSession.current = null; setDragged(null) }} onClick={() => model.service.open(v.id)} title={`${v.title} · 拖动以移动`}>{v.title}</button>)}</div>}
        {!list.length && <span className="wb-region-label">{labels[name]}</span>}
        <div className="wb-region-actions">{active && <>
          <select aria-label={`移动 ${active.title} 到`} value="" onChange={e => { if (e.target.value) move(active.id, e.target.value as Region) }}>
            <option value="">移动…</option>{regions.filter(r => r !== name).map(r => <option key={r} value={r}>{labels[r]}</option>)}
          </select>
          <button aria-label={`关闭${active.title}`} title="关闭视图" onClick={() => model.service.close(active.id)}>×</button>
        </>}{name !== 'main' && <button aria-label={`收起${labels[name]}`} title={`收起${labels[name]}`} onClick={() => model.collapse(name, true)}>−</button>}</div>
        {name === 'main' && <><div className="wb-actions">{slot('toolbar')}</div><div className="wb-layout-actions">
          {auxiliary.map(r => <button key={r} disabled={!has[r]} aria-label={`${layout.collapsed[r] ? '展开' : '收起'}${labels[r]}`} title={`${labels[r]}${has[r] ? '' : '（无视图）'}`} aria-pressed={has[r] && !layout.collapsed[r]} onClick={() => model.collapse(r, !layout.collapsed[r])}><RegionIcon region={r} /></button>)}
          <button title="恢复默认位置和尺寸" aria-label="重置布局" onClick={reset}>↺</button>
        </div></>}
      </header>
      {name === 'left' && (moduleNav.length > 0 || navItems.length > 0) && <nav className="wb-nav" aria-label="导航">{moduleNav}{navItems}</nav>}
      <div className="wb-content" ref={node => { hosts.current[name] = node }} />
      {!active && name === 'main' && <div className="wb-empty"><span className="wb-empty-mark" aria-hidden="true">O</span><h1>工作区已就绪</h1><p>从左侧打开扩展，或选择一个视图。</p><small>拖动视图标题可移动位置 · 拖动分隔线可调整大小</small></div>}
    </section>
  }
  const panel = (name: Exclude<Region, 'main'>) => <Panel key={name} id={`wb-${name}`} panelRef={value => { panels.current[name] = value }}
    collapsible collapsedSize="0%" defaultSize={has[name] ? `${sizes.current[name]}%` : '0%'}
    minSize={has[name] ? (name === 'left' || name === 'right' ? '12%' : '10%') : '0%'} maxSize={has[name] ? '40%' : '0%'}>
    {region(name)}
  </Panel>
  const separator = (name: Exclude<Region, 'main'>) => <Separator key={`sep-${name}`} id={`resize-${name}`} aria-label={`调整${labels[name]}大小`}
    className={`wb-separator ${has[name] ? '' : 'wb-separator-empty'}`} disabled={!has[name]} onDoubleClick={() => panels.current[name]?.resize(name === 'top' ? '18%' : name === 'bottom' ? '24%' : '22%')} />
  const resized = (axis: readonly Exclude<Region, 'main'>[]) => (values: Record<string, number>, meta: { isUserInteraction: boolean }) => {
    if (!meta.isUserInteraction) return
    for (const name of axis) {
      const value = values[`wb-${name}`]
      if (value > 0) sizes.current[name] = value
      if (has[name]) model.collapse(name, value === 0)
    }
  }
  const reset = () => {
    sizes.current = { left: 22, right: 22, top: 18, bottom: 24 }
    model.resetLayout()
    for (const name of auxiliary) if (has[name]) panels.current[name]?.resize(`${sizes.current[name]}%`)
  }
  const Full = full?.component
  const activeViews = views.filter(v => v.presentation === 'region' && selection[model.regionOf(v)!] === v.id)
  return <div className="wb"><style>{styles}</style>
    <div ref={workspace} tabIndex={-1} hidden={!!full} inert={!!full || hasModal} aria-hidden={!!full} data-testid="workspace">
      <div className="wb-body">
        <div className="wb-layout">
          <Group id="wb-vertical" orientation="vertical" className="wb-group" onLayoutChanged={resized(['top', 'bottom'])}>
            {panel('top')}{separator('top')}
            <Panel id="wb-center" minSize="20%">
              <Group id="wb-horizontal" className="wb-group" onLayoutChanged={resized(['left', 'right'])}>
                {panel('left')}{separator('left')}
                <Panel id="wb-main" minSize="20%">{region('main')}</Panel>
                {separator('right')}{panel('right')}
              </Group>
            </Panel>
            {separator('bottom')}{panel('bottom')}
          </Group>
          {dragged && <div className="wb-drop-targets" onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}>
            {regions.map(r => <div key={r} className={`wb-drop-${r}`} data-drop-region={r} onDrop={e => { e.preventDefault(); if (e.dataTransfer.getData('application/x-ordessa-view') === dragged) move(dragged, r); else setDragged(null) }}>移至{labels[r]}</div>)}
          </div>}
        </div>
      </div>
      <footer className="wb-status"><span className="wb-status-dot" />{slot('navigation', 'utility')}{slot('statusbar')}
        <button aria-label="打开设置" onClick={openSettings}>设置</button><span className="wb-status-end">本地工作台</span></footer>
    </div>
    {activeViews.map(v => <ViewSurface key={v.id} view={v} region={model.regionOf(v)!} hosts={hosts} />)}
    {Full && <section className="wb-full" data-testid="full-page" aria-label={full.title}>
      <header className="wb-bar"><button ref={back} onClick={() => model.service.close(full.id)}>← 返回工作区</button><h1>{full.title}</h1></header>
      <div className="wb-full-content"><Boundary key={full.id}><Full /></Boundary></div>
    </section>}
    {overlayStack.length > 0 && <div className="wb-overlays" data-testid="wb-overlays">
      {overlayStack.map((entry, index) => {
        const inert = overlayStack.slice(index + 1).some(later => presentationOf(later) !== 'popover')
        if (entry.overlayId === SETTINGS_OVERLAY_ID) return <SettingsOverlay key={entry.key} entry={entry} sections={sections} inert={inert}
          close={() => model.closeOverlayInstance(entry.key)} workspace={workspace} />
        const def = overlayDefs.find(o => o.id === entry.overlayId)
        if (!def) return null
        const Content = def.component
        return <OverlaySurface key={entry.key} entry={entry} title={def.title} presentation={presentationOf(entry)} inert={inert}
          close={() => model.closeOverlayInstance(entry.key)} workspace={workspace}>
          <Content close={() => model.closeOverlayInstance(entry.key)} />
        </OverlaySurface>
      })}
    </div>}
    {error && <div role="alert" className="wb-error">{error}<button onClick={() => setError('')}>关闭提示</button></div>}
  </div>
}
