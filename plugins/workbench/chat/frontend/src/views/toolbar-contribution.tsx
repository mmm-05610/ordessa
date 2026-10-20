import { Component, useEffect, useState, type ReactNode } from 'react'
import type { UiBinding, UiComponentKey, UiScope } from '@ordessa/ui-components/api'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import type { ChatContributionContext, ChatContributionView } from '@extensions/ordessa.chat-api/contract.js'
import { ConnectionBadge } from './connection-badge'
import { connectionBadgeKey } from '../state/keys'

interface ToolbarProps { view: ChatContributionView; ui?: UiScope; context: ChatContributionContext }

class ContributionBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  override render() {
    return this.state.failed ? <span role="alert">此工具栏贡献渲染失败。</span> : this.props.children
  }
}

export function ToolbarContribution(props: ToolbarProps) {
  return <ContributionBoundary key={`${props.view.keyId}:${props.view.keyMajor}`}><ToolbarPosition {...props}/></ContributionBoundary>
}

function ToolbarPosition({ view, ui, context }: ToolbarProps) {
  const badge = view.keyId === connectionBadgeKey.id && view.keyMajor === connectionBadgeKey.major
  const hasProject = view.project !== undefined
  const key = view.key
  const [bound, setBound] = useState<{ ui: UiScope; key: UiComponentKey<unknown>; binding: UiBinding<unknown> } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  useEffect(() => {
    setBound(null); setFailure(null)
    // The read-side key preserves registration identity. A legacy view that
    // erased it cannot be safely rebound by manufacturing an equal-looking key.
    if (!ui || badge || !hasProject || !key) return
    let binding: UiBinding<unknown>
    try { binding = ui.bind(key, { required: false }) }
    catch (error) { setFailure(error instanceof Error ? error.message : String(error)); return }
    setBound({ ui, key, binding })
    return () => { binding.dispose() }
  }, [ui, badge, key, hasProject])

  if (!view.project) return null
  const projected = view.project(context)
  if (projected.hidden) return null
  if (badge) return <ConnectionBadge {...projected.props as { readonly status: string }}/>
  if (failure) return <span role="alert">工具栏组件绑定失败：{failure}</span>
  if (!bound || bound.ui !== ui || bound.key !== key) return null
  return <ComponentOutlet binding={bound.binding} value={projected.props} missing={null}/>
}
