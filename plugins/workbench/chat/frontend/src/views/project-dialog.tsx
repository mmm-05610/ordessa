// Global project selection dialog (input-spec US4 N01–N06), hosted in the
// Workbench's existing overlay mechanism — Chat builds no second floating
// layer. Projects come ONLY from the sessions facade's workspace table (no
// second project store); the same name under a different Server instance stays
// distinguishable because each row carries its connection title. Add-project
// uses the existing native picker; cancel performs zero backend calls and zero
// channel initialization (N04) — the dialog only ever calls refresh/list.
// Errors are retryable in place; remote results are guarded by the request
// revision captured at open time (stale async results never update a new view).
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AgentSessions, AgentWorkspaceSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'

export interface ProjectDialogProps {
  readonly service: AgentSessions
  /** Live workspace snapshot from the facade subscription. */
  readonly snapshot: AgentWorkspaceSnapshot
  readonly close: () => void
  /** Called with the selected project after `selectWorkspace` succeeded; the
   * dialog itself never opens a channel. */
  readonly onProjectSelected: (projectId: string) => void
}

interface ProjectRow {
  readonly id: string
  readonly path: string
  readonly label: string
  readonly connectionId: string
  readonly connectionTitle: string
}

export function ProjectDialog({ service, snapshot, close, onProjectSelected }: ProjectDialogProps) {
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [requestRevision, setRequestRevision] = useState(0)
  const stale = useRef(false)
  useEffect(() => {
    stale.current = false
    return () => { stale.current = true }
  }, [requestRevision])

  const agent = snapshot.agent
  const connections = useMemo(() => new Map(
    (snapshot.available ?? []).map(conn => [conn.id, conn.title] as const)), [snapshot.available])
  const rows = useMemo<ProjectRow[]>(() => {
    const workspaces = agent?.workspaces?.items ?? []
    const connectionId = snapshot.selectedConnectionId ?? ''
    return workspaces.map(workspace => ({
      id: workspace.id,
      path: workspace.normalizedPath,
      label: workspace.normalizedPath.split('/').filter(Boolean).at(-1) ?? workspace.normalizedPath,
      connectionId,
      connectionTitle: connections.get(connectionId) ?? connectionId,
    }))
  }, [agent?.workspaces?.items, connections, snapshot.selectedConnectionId])

  const filtered = rows.filter(row => row.path.toLowerCase().includes(filter.trim().toLowerCase()))
  const projectCapable = agent?.connection.capabilities.workspaces === 'supported'

  const select = async (projectId: string) => {
    setBusy(true)
    setError('')
    try {
      await service.selectWorkspace?.(projectId)
      if (!stale.current) onProjectSelected(projectId)
    } catch (cause) {
      if (!stale.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (!stale.current) setBusy(false)
    }
  }

  const addProject = async () => {
    setBusy(true)
    setError('')
    try {
      const picker = (globalThis as { projectDirectory?: { choose(): Promise<string | undefined> } }).projectDirectory
      if (!picker) {
        setError('当前环境没有可用的文件夹选择器，无法添加项目。')
        return
      }
      const path = await picker.choose()
      if (!path) return // user cancelled the picker: zero backend calls
      await service.addWorkspace?.(path)
      if (!stale.current) setRequestRevision(revision => revision + 1)
    } catch (cause) {
      if (!stale.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (!stale.current) setBusy(false)
    }
  }

  return (
    <div className="chat-dialog-backdrop" data-testid="chat-project-dialog" role="dialog" aria-label="选择项目">
      <div className="chat-dialog">
        <header className="chat-dialog-head">
          <h2>选择项目</h2>
          <button type="button" className="chat-ghost-action" data-action="close-dialog" data-testid="chat-project-close"
            onClick={close}>关闭</button>
        </header>
        <div className="chat-dialog-search">
          <input placeholder="搜索项目…" value={filter} data-testid="chat-project-search"
            autoFocus onChange={event => setFilter(event.currentTarget.value)} />
        </div>
        {!projectCapable && agent && (
          <p role="status" className="chat-dialog-note" data-state="unsupported">
            当前连接不支持按项目创建会话。
          </p>
        )}
        {agent?.workspaces?.state === 'loading' && <p role="status" className="chat-dialog-note" data-state="loading">正在加载项目…</p>}
        {agent?.workspaces?.state === 'error' && (
          <div className="chat-dialog-error" role="alert" data-state="error">
            <span>项目列表加载失败。</span>
            <button type="button" className="chat-ghost-action" data-action="refresh-projects" disabled={busy}
              onClick={() => { void service.refreshWorkspaces?.() }}>就地重试</button>
          </div>
        )}
        <div className="chat-dialog-list" data-testid="chat-project-list">
          {filtered.map(row => (
            <button key={`${row.connectionId}:${row.id}`} type="button" className="chat-dialog-row"
              data-project-id={row.id} disabled={busy}
              onClick={() => void select(row.id)}>
              <span className="chat-dialog-row-label">{row.label}</span>
              <span className="chat-dialog-row-path" title={row.path}>{row.path}</span>
              <span className="chat-dialog-row-source">{row.connectionTitle}</span>
            </button>
          ))}
          {agent?.workspaces?.state === 'ready' && filtered.length === 0 && (
            <p className="chat-dialog-note" data-state="empty">没有匹配的项目。</p>
          )}
        </div>
        <footer className="chat-dialog-foot">
          <button type="button" data-action="add-project" data-testid="chat-project-add" disabled={busy || !snapshot.selectedConnectionId}
            onClick={() => void addProject()}>添加项目…</button>
          {error && <span role="alert" className="chat-error">{error}</span>}
        </footer>
      </div>
    </div>
  )
}
