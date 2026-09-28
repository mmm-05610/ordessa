// Approval / interaction operation surface (input-spec US5 C02/C03; migrated
// owner of the old ordessa.agent-conversation interaction-card per the Z2
// migration table — original action semantics preserved verbatim: answers are
// only ever built from service-provided choices/fields, an `approval` kind
// with no choices offers nothing, and the interactions capability gates the
// whole surface). One unique operation surface per pending interaction;
// responding/resolved/expired disable actions; a resolved approval never
// renders as tool success.
import { useState } from 'react'
import type { AgentInteraction, InteractionAnswer } from '@extensions/ordessa.agent-contracts/contract.js'

/** A connector's negative verdict on its interaction channel must not become
 * a successful-looking response attempt (FC-0029). */
const canAnswer = (capability: 'supported' | 'unsupported' | 'unknown' | 'unavailable' | undefined) =>
  capability !== 'unsupported' && capability !== 'unavailable'

export interface ApprovalPanelProps {
  readonly interactions: readonly AgentInteraction[]
  readonly interactionsCapability?: 'supported' | 'unsupported' | 'unknown' | 'unavailable'
  readonly respond: (interactionId: string, answer: InteractionAnswer) => Promise<void>
}

export function ApprovalPanel({ interactions, interactionsCapability, respond }: ApprovalPanelProps) {
  const [values, setValues] = useState<Record<string, Record<string, string>>>({})
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<string | undefined>(undefined)
  const respondable = canAnswer(interactionsCapability)
  const actionable = interactions.filter(item => item.state === 'pending' || item.state === 'responding')
  const hiddenCount = Math.max(0, actionable.length - 3)
  const fieldValue = (interactionId: string, fieldId: string) => values[interactionId]?.[fieldId] ?? ''
  const change = (interactionId: string, fieldId: string, value: string) =>
    setValues(current => ({ ...current, [interactionId]: { ...current[interactionId], [fieldId]: value } }))
  const submit = async (interactionId: string, answer: InteractionAnswer) => {
    if (busyId !== undefined) return
    setBusyId(interactionId)
    setError('')
    try { await respond(interactionId, answer) } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally { setBusyId(undefined) }
  }
  if (actionable.length === 0) return null
  return (
    <div className="chat-approvals" data-testid="chat-approvals" data-count={actionable.length}>
      {actionable.slice(0, 3).map(item => {
        const pending = item.state === 'pending' && respondable
        const busy = busyId === item.id
        return (
          <div key={item.id} className="chat-approval" data-state={item.state} data-kind={item.kind}
            data-interaction-id={item.id} data-testid="chat-approval">
            <div className="chat-approval-head">
              <strong>{item.title}</strong>
              <span className="chat-approval-state">{item.state}</span>
            </div>
            {item.detail && <p className="chat-approval-detail">{item.detail}</p>}
            {item.state === 'pending' && !respondable && (
              <p role="status" className="chat-approval-muted">当前连接无法接收回应，操作不可用。</p>
            )}
            {item.state === 'responding' && <p role="status" className="chat-approval-muted">回应已提交，等待服务确认。</p>}
            {pending && item.fields?.map(field => (
              <fieldset key={field.id} className="chat-approval-field" disabled={busy}>
                <legend>{field.title}</legend>
                {field.detail && <p>{field.detail}</p>}
                {field.choices?.length
                  ? <select aria-label={field.title} value={fieldValue(item.id, field.id)}
                      onChange={event => change(item.id, field.id, event.target.value)}>
                      <option value="">请选择…</option>
                      {field.choices.map(choice => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
                    </select>
                  : <label>{field.secret ? '保密回应' : '回应'}
                      {item.kind === 'editor'
                        ? <textarea value={fieldValue(item.id, field.id)} onChange={event => change(item.id, field.id, event.target.value)} />
                        : <input type={field.secret ? 'password' : 'text'} value={fieldValue(item.id, field.id)}
                            onChange={event => change(item.id, field.id, event.target.value)} />}
                    </label>}
              </fieldset>
            ))}
            <div className="chat-approval-actions">
              {pending && item.fields?.length && (
                <>
                  <button type="button" data-action="send-answer"
                    disabled={busy || item.fields.some(field => !fieldValue(item.id, field.id))}
                    onClick={() => void submit(item.id, { kind: 'answers', answers: Object.fromEntries(item.fields!.map(field => [field.id, [fieldValue(item.id, field.id)]])) })}>
                    发送回应
                  </button>
                  <button type="button" data-action="cancel" disabled={busy}
                    onClick={() => void submit(item.id, { kind: 'cancel' })}>取消</button>
                </>
              )}
              {pending && !item.fields?.length && item.choices?.map(choice => (
                <button key={choice.id} type="button" data-action="choice" data-choice-id={choice.id} disabled={busy}
                  onClick={() => void submit(item.id, { kind: 'choice', choiceId: choice.id })}>{choice.label}</button>
              ))}
              {pending && !item.fields?.length && item.kind === 'confirm' && (
                <>
                  <button type="button" data-action="confirm" disabled={busy}
                    onClick={() => void submit(item.id, { kind: 'confirm', confirmed: true })}>确认</button>
                  <button type="button" data-action="decline" disabled={busy}
                    onClick={() => void submit(item.id, { kind: 'confirm', confirmed: false })}>拒绝</button>
                </>
              )}
              {pending && !item.fields?.length && (item.kind === 'input' || item.kind === 'editor') && (
                <>
                  <input aria-label="回应" value={fieldValue(item.id, 'answer')}
                    onChange={event => change(item.id, 'answer', event.target.value)} />
                  <button type="button" data-action="send-text" disabled={busy}
                    onClick={() => void submit(item.id, { kind: 'text', value: fieldValue(item.id, 'answer') })}>发送回应</button>
                  <button type="button" data-action="cancel" disabled={busy}
                    onClick={() => void submit(item.id, { kind: 'cancel' })}>取消</button>
                </>
              )}
            </div>
          </div>
        )
      })}
      {hiddenCount > 0 && <div className="chat-approvals-more" data-testid="chat-approvals-more">还有 {hiddenCount} 个待处理项</div>}
      {error && <p role="alert" className="chat-error">{error}</p>}
    </div>
  )
}
