import { useState, useSyncExternalStore, useRef, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import type { AgentConnectionWorkspace } from '@extensions/ordessa.agent-contracts/contract.js'

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)

/** Statusbar connection indicator with a popover for harness selection and reconnection.
 * Pure increment: no region view is registered (F1-0011); the footer stays collapsed by default. */
export function ConnectionStatus({ workspace }: { workspace: AgentConnectionWorkspace }) {
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot)
  const [open, setOpen] = useState(false)
  const [actionError, setActionError] = useState('')
  const toggle = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({left:8, top:8})
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const a=toggle.current?.getBoundingClientRect(), b=menu.current?.getBoundingClientRect()
      if (!a || !b) return
      setPosition({left:Math.max(8,Math.min(a.left,window.innerWidth-b.width-8)),top:Math.max(8,a.top-b.height-8)})
    }
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menu.current?.contains(event.target) && !toggle.current?.contains(event.target)) setOpen(false)
    }
    const key = (event: KeyboardEvent) => { if(event.key==='Escape') { setOpen(false); toggle.current?.focus() } }
    place()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(place)
    if(menu.current) observer?.observe(menu.current)
    window.addEventListener('resize',place)
    document.addEventListener('scroll',place,true)
    document.addEventListener('pointerdown',outside)
    document.addEventListener('keydown',key)
    return () => { observer?.disconnect(); window.removeEventListener('resize',place);document.removeEventListener('scroll',place,true);document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key) }
  }, [open])
  const perform = (action: () => Promise<void>) => { setActionError(''); void action().catch(error => setActionError(errorText(error))) }
  const selected = state.selectedConnectionId
  const pending = workspace.releaseCleanup?.() ?? state.pendingReleases ?? []
  const status = !selected ? 'disconnected'
    : state.connectingId === selected ? 'connecting'
    : state.agent?.connection.status ?? 'disconnected'
  return <div className="conn-status">
    <style>{styles}</style>
    <button ref={toggle} className="conn-status-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <span className={`conn-dot conn-dot-${status}`} aria-hidden="true" />
      <span>{selected ? `Agents · ${status}` : '选择 Harness'}</span>
    </button>
    {open && createPortal(<div ref={menu} style={position} className="conn-popover" role="group" aria-label="Agent connections">
      <style>{styles}</style>
      {state.available.length
        ? state.available.map(item => <button key={item.id} data-connection-id={item.id}
            className={selected === item.id ? 'conn-selected' : ''}
            aria-pressed={selected === item.id}
            onClick={() => perform(async () => { await workspace.selectConnection(item.id); setOpen(false) })}>
            <span>{item.title}</span>
            {selected === item.id && <small>{state.connectingId === item.id ? 'connecting' : status}</small>}
          </button>)
        : <p className="conn-empty">No agent connector is enabled.</p>}
      {selected && <button onClick={() => perform(() => workspace.reconnect(selected))}>Reconnect</button>}
      {/* Evicted clients whose backend stand-down is outstanding, in its explicitly announced
          state: in-flight never looks confirmed, and a failure shows its reason. The workspace
          re-publishes on every transition, so this line appears without any user action; the
          retry is an explicit action through the same perform channel as every other operation. */}
      {pending.length > 0 && <p role="alert" className="conn-error">
        Backend release pending: {pending.map(item => `${item.connectionId}: ${item.status === 'failed' ? item.reason : item.status}`).join('; ')}
      </p>}
      {pending.length > 0 && workspace.retryReleaseCleanup &&
        <button onClick={() => perform(() => workspace.retryReleaseCleanup!())}>Retry backend release</button>}
      {(actionError || state.error) && <p role="alert" className="conn-error">{actionError || state.error}</p>}
    </div>,document.body)}
  </div>
}

const styles = `
.conn-status { position: relative; }
.conn-status-toggle { display: inline-flex; align-items: center; gap: 6px; border: none; background: none; cursor: pointer; font: inherit; padding: 2px 6px; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; background: #9e9e9e; }
.conn-dot-connected { background: #2e7d32; }
.conn-dot-connecting { background: #f9a825; }
.conn-dot-error { background: #c62828; }
.conn-popover { position: fixed; max-height:calc(100vh - 16px); overflow:auto; max-width:calc(100vw - 16px); min-width: 220px; display: flex; flex-direction: column; gap: 4px; -webkit-app-region:no-drag;
  background: #fff; border: 1px solid #ccc; border-radius: 6px; padding: 8px; box-shadow: 0 4px 12px rgba(0,0,0,.15); z-index: 30; }
.conn-popover button { text-align: left; border: 1px solid transparent; background: none; cursor: pointer; font: inherit; padding: 4px 6px; border-radius: 4px; }
.conn-popover button:hover { background: #f0f0f0; }
.conn-popover button.conn-selected { border-color: #2e7d32; }
.conn-popover .conn-empty { margin: 0; color: #666; }
.conn-popover .conn-error, .conn-error { margin: 0; color: #c62828; }
`
