import { useLayoutEffect, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import type { DragEvent } from 'react'
import type { Region, View } from '@extensions/ordessa.contracts/contract.js'
import { labels, RegionActions, ViewTabs } from './region-header'

/** Workspace identity shown in the sidebar header. The Workbench owns no
 * workspace/project data (W07): with no registered source the fixed, honest
 * label is used — never a fabricated account or remote identity. */
export const SIDEBAR_IDENTITY = '工作区'

export interface SidebarProps {
  list: readonly View[]
  active: View | undefined
  /** The sidebar is operable: it holds a left view or any registered chrome
   * (module / navigation / bottom contributions). Chrome never depends on the
   * left view count alone. */
  usable: boolean
  collapsed: boolean
  nav: ReactNode | null
  openView(id: string): void
  moveView(id: string, region: Region): void
  closeView(id: string): void
  setCollapsed(collapsed: boolean): void
  onTabDragStart(event: DragEvent<HTMLButtonElement>, view: View): void
  onTabDragEnd(): void
  /** Registers the left content host in the shell's ViewSurface `hosts` map —
   * the same callback-ref wiring every other region uses. */
  contentRef(node: HTMLDivElement | null): void
  footerRef: RefObject<HTMLDivElement | null>
}

/** Four-segment sidebar (Header / Navigation / Content / Footer). The
 * [data-region="left"] section, its tab strip and region actions keep their
 * pinned shapes; the column structure follows the fixed ZCode aside skeleton
 * (PROVENANCE.md: structural extraction only, Ordessa contributions inside). */
export function Sidebar({ list, active, usable, collapsed, nav, ...actions }: SidebarProps) {
  return <section className="wb-region wb-left wb-sidebar" data-region="left" aria-label={labels.left}
    data-active-view={list.length === 1 ? active?.title : undefined} inert={!usable || collapsed}>
    <header className="wb-sidebar-header">
      <strong className="wb-sidebar-identity">{SIDEBAR_IDENTITY}</strong>
      <ViewTabs name="left" list={list} active={active} open={actions.openView} onDragStart={actions.onTabDragStart} onDragEnd={actions.onTabDragEnd} />
      {!list.length && <span className="wb-region-label">{labels.left}</span>}
      {usable && !collapsed && <button className="wb-sidebar-collapse" aria-label={`收起${labels.left}`} title={`收起${labels.left}`} onClick={() => actions.setCollapsed(true)}>−</button>}
      <RegionActions name="left" active={active} showCollapse={!usable} move={actions.moveView} close={actions.closeView} collapse={() => actions.setCollapsed(true)} />
    </header>
    {nav && <div className="wb-sidebar-nav">{nav}</div>}
    <div className="wb-content wb-sidebar-content" ref={actions.contentRef} />
    <div className="wb-sidebar-footer" ref={actions.footerRef} />
  </section>
}

/** Keyboard-reachable sidebar restore control, placed in the main-region
 * header (no permanent left rail). Enter activates it explicitly; the native
 * click path stays for mouse users. */
export function SidebarRestoreButton({ expand }: { expand(): void }) {
  return <button className="wb-sidebar-restore" aria-label={`展开${labels.left}`} title={`展开${labels.left}`} onClick={expand}
    onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); expand() } }}>«</button>
}

/**
 * One footer, one mount point: the bottom contributions portal into a single
 * stable container element that moves between the expanded sidebar footer and
 * the compact workspace-bottom band. The container is never duplicated, so a
 * contribution mounts exactly once and keeps its instance and subscriptions
 * across collapse/expand (same stable-container trick as ViewSurface).
 */
export function FooterSurface({ sidebarHost, bandHost, inSidebar, children }: {
  sidebarHost: RefObject<HTMLDivElement | null>; bandHost: RefObject<HTMLDivElement | null>
  inSidebar: boolean; children: ReactNode
}) {
  const [node] = useState(() => { const el = document.createElement('div'); el.className = 'wb-status'; return el })
  useLayoutEffect(() => {
    (inSidebar ? sidebarHost : bandHost).current?.appendChild(node)
  }, [inSidebar, node, sidebarHost, bandHost])
  useLayoutEffect(() => () => { node.remove() }, [node])
  return createPortal(children, node)
}
