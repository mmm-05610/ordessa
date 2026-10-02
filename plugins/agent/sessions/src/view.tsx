import { useState, useSyncExternalStore } from 'react'
import { Collapsible } from 'radix-ui'
import type { AgentSessionInfo, AgentSessions, AgentSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'
import { projectSessionGroups, sessionActivity, workspaceLabel } from './projection'
import { styles } from './styles'

function useWorkspace(service: AgentSessions) { return useSyncExternalStore(service.subscribe, service.getSnapshot) }
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)
const belongsTo = (session: AgentSessionInfo, id: string, path: string) =>
  session.workspaceId === id || session.workspaceId?.replace(/\/+$/, '') === path.replace(/\/+$/, '')

function SessionItem({ session, agent, open }: { session: AgentSessionInfo; agent: AgentSnapshot; open: (id: string) => void }) {
  const activity = sessionActivity(agent, session.id)
  return <button className="agent-session-item" aria-current={agent.selectedSessionId === session.id ? 'true' : undefined}
    onClick={() => open(session.id)} title={session.title}>
    <strong>{session.title}</strong>
    {activity.openRun && <small className="agent-session-state" data-status="running">Running</small>}
    {activity.awaiting && <small className="agent-session-state" data-status="awaiting">Awaiting answer</small>}
  </button>
}

export function SessionBrowser({ service }: { service: AgentSessions }) {
  const state = useWorkspace(service), agent = state.agent
  const [actionError, setActionError] = useState('')
  const perform = (action: () => Promise<void>) => { setActionError(''); void action().catch(error => setActionError(errorText(error))) }
  const open = (id: string) => perform(() => service.openSession(id))
  const groups = projectSessionGroups(agent?.sessions ?? [])
  const showGroups = groups.length > 1 || groups.some(group => !group.standalone)
  const projects = agent?.workspaces?.items ?? []
  const projectCapable = agent?.connection.capabilities.workspaces === 'supported'
  const recent = [...(agent?.sessions ?? [])].sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '')).slice(0, 8)
  const addProject = () => perform(async () => {
    const path = await window.projectDirectory?.choose()
    if (path) await service.addWorkspace?.(path)
  })
  return <section className="agent-panel agent-sessions"><style>{styles}</style>
    {!state.selectedConnectionId && <p className="agent-empty">Choose a connection from the status bar.</p>}
    {actionError && <p role="alert" className="agent-error">{actionError}</p>}
    <div className="agent-sidebar-primary">
      <button className="agent-new-session" disabled={!agent || agent.connection.status !== 'connected'}
        onClick={() => service.startDraft?.()}>New session</button>
      {projectCapable && <button className="agent-add-project" disabled={!agent || agent.connection.status !== 'connected'}
        onClick={addProject}><span aria-hidden="true">＋</span> Add project</button>}
    </div>
    {state.draft?.active && <details className="agent-draft">
      <summary className="agent-draft-summary" title="修改当前草稿的项目，不会创建会话">
        <span aria-hidden="true">▱</span>
        <span>{state.draft.workspaceId
          ? workspaceLabel(projects.find(project => project.id === state.draft?.workspaceId)?.normalizedPath ?? state.draft.workspaceId)
          : '选择项目'}</span>
        <span className="agent-draft-edit">修改</span>
      </summary>
      <div className="agent-actions"><button disabled={!agent || agent.connection.status !== 'connected'}
        onClick={() => perform(() => Promise.resolve(service.refreshWorkspaces?.()))}>Refresh projects</button>
        <button onClick={() => service.discardDraft?.()}>Discard draft</button></div>
      {agent?.workspaces?.state === 'loading' && <p role="status" className="agent-empty">Loading projects…</p>}
      {agent?.workspaces?.state === 'error' && <p role="alert" className="agent-error">Project list failed. Refresh projects to try again.</p>}
      {agent?.workspaces && agent.workspaces.state !== 'loading' && <div className="agent-project-picker">{projects.map(project => <button key={project.id}
        aria-pressed={state.draft?.workspaceId === project.id}
        onClick={() => perform(async () => { await service.selectWorkspace?.(project.id) })}>
        <span>{project.normalizedPath}</span></button>)}</div>}
      {state.draft.blockReason && <p className="agent-notice">Send is blocked until a valid project is selected.</p>}
    </details>}
    {state.selectedConnectionId && <div className="agent-actions agent-refresh"><button disabled={!agent || agent.connection.status !== 'connected'}
      onClick={() => perform(() => service.refreshSessions())}>Refresh</button></div>}
    {agent?.sessionList === 'loading' && <p role="status" className="agent-empty">Loading sessions…</p>}
    {agent?.sessionList === 'partial' && <p className="agent-notice">Only part of the history is available.</p>}
    {agent?.sessionList === 'error' && <p role="alert" className="agent-error">Session list failed. Refresh to try again.</p>}
    {projectCapable ? <div className="agent-sidebar-sections">
      <div className="agent-list-heading">Projects</div>
      {projects.length === 0 && <p className="agent-empty">No projects yet. Add a folder to start.</p>}
      {projects.map(project => <Collapsible.Root key={project.id} defaultOpen={project.id === agent?.workspaces?.selectedWorkspaceId} className="agent-project-group">
        <div className="agent-project-row">
          <Collapsible.Trigger className="agent-project-expand" aria-label={`Expand ${workspaceLabel(project.normalizedPath)}`}>▸</Collapsible.Trigger>
          <button className="agent-project-name" title={project.normalizedPath} aria-current={project.id === agent?.workspaces?.selectedWorkspaceId ? 'true' : undefined}
            onClick={() => perform(() => Promise.resolve(service.selectWorkspace?.(project.id)))}>{workspaceLabel(project.normalizedPath)}</button>
          <button className="agent-project-new" aria-label={`New session in ${workspaceLabel(project.normalizedPath)}`}
            onClick={() => perform(async () => { await service.selectWorkspace?.(project.id); service.startDraft?.() })}>＋</button>
        </div>
        <Collapsible.Content className="agent-project-content">{agent?.sessions.filter(session => belongsTo(session, project.id, project.normalizedPath)).map(session =>
          <SessionItem key={session.id} session={session} agent={agent} open={open} />)}</Collapsible.Content>
      </Collapsible.Root>)}
      <div className="agent-list-heading agent-recent-heading">Recent</div>
      {recent.length === 0 && <p className="agent-empty">No sessions yet.</p>}
      <div className="agent-session-list">{agent && recent.map(session => <SessionItem key={session.id} session={session} agent={agent} open={open} />)}</div>
    </div> : <div className="agent-session-list">{groups.map(group => <div key={group.key} className="agent-session-group-block">
      {showGroups && <p className="agent-session-group">{group.title}</p>}
      {group.sessions.map(session => agent && <SessionItem key={session.id} session={session} agent={agent} open={open} />)}
    </div>)}</div>}
    {!projectCapable && agent?.sessionList === 'ready' && !agent.sessions.length && <p className="agent-empty">No sessions yet. Start one above.</p>}
  </section>
}
