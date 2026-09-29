// MCP Settings section (ux.md「Settings 的 MCP 区」). Contributed to the
// Workbench composition under owner id `ordessa.asset.mcp.settings`; the
// Workbench owns the page and the empty state, this component owns only its
// slice (packages/workbench renders registered sections verbatim).
//
// Wording discipline enforced here and asserted in tests:
// * a probe result renders as 探测成功（无凭据） — never 已连接 / 连接成功;
// * saving produces a CANDIDATE revision; approval is the separate
//   「批准并用于选择」action;
// * secretRef values are credential ids through the CredentialProvider
//   abstraction; with no provider installed those fields are read-only and
//   the revision cannot be approved/applied;
// * the probe button states its credential-less scope from the returned facts.

import { useCallback, useEffect, useState } from 'react'
import type { McpCanonicalDefinition, McpDefinitionSummary, McpProbeFacts, McpRevisionView, McpWireValue } from './dto'
import type { McpWireClient } from './wire'
import { McpWireError } from './wire'
import type { CredentialProvider, CredentialReference } from './credentials'

/** One editable env/header entry: the value is either a readable literal or a
 * credential REFERENCE (id only — plaintext never exists on this surface). */
export interface ValueRow {
  readonly key: string
  readonly kind: 'literal' | 'secretRef'
  readonly value: string
}

export function rowsToWireMap(rows: readonly ValueRow[]): Record<string, McpWireValue> {
  const out: Record<string, McpWireValue> = {}
  for (const row of rows) {
    if (!row.key) continue
    out[row.key] = row.kind === 'literal' ? { literal: row.value } : { secretRef: row.value }
  }
  return out
}

export function wireMapToRows(map: Readonly<Record<string, McpWireValue>> | undefined): ValueRow[] {
  return Object.entries(map ?? {}).map(([key, value]) =>
    'literal' in value ? { key, kind: 'literal' as const, value: value.literal } : { key, kind: 'secretRef' as const, value: value.secretRef })
}

export function definitionHasSecretRef(definition: McpCanonicalDefinition): boolean {
  const t = definition.transport
  const map = 'stdio' in t ? t.stdio.env : t.remote.headers
  return Object.values(map ?? {}).some(value => 'secretRef' in value)
}

export interface McpSettingsProps {
  readonly client: McpWireClient
  /** Absent = the Credential service is not installed: secretRef fields go
   * read-only and approval/apply is blocked (no internal vault is invented). */
  readonly credentials?: CredentialProvider
}

interface EditorState {
  readonly mode: 'new' | 'edit'
  readonly definitionId?: string
  readonly name: string
  readonly transport: 'stdio' | 'remote'
  readonly command: string
  readonly args: string
  readonly url: string
  readonly values: ValueRow[]
  /** latest stored revision for the CAS expectedVersion; 0 for a new id. */
  readonly expectedVersion: number
}

let operationSequence = 0
export const nextOperationKey = () => `settings-op-${Date.now()}-${++operationSequence}`

export function McpSettingsSection({ client, credentials }: McpSettingsProps) {
  const [rows, setRows] = useState<readonly McpDefinitionSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [candidate, setCandidate] = useState<{ definitionId: string; revision: number; hasSecretRef: boolean } | null>(null)
  const [probe, setProbe] = useState<{ label: string; facts: McpProbeFacts } | null>(null)
  const [refusal, setRefusal] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [credentialsList, setCredentialsList] = useState<readonly CredentialReference[] | null>(null)

  const reload = useCallback(async () => {
    try { setRows(await client.listDefinitions()); setListError(null) }
    catch (error) { setRows(null); setListError(describe(error)) }
  }, [client])
  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!credentials) return
    let settled = false
    void credentials.listCredentials().then(list => { if (!settled) setCredentialsList(list) }, () => { if (!settled) setCredentialsList([]) })
    return () => { settled = true }
  }, [credentials])

  const openEditor = async (row: McpDefinitionSummary) => {
    setProbe(null); setRefusal(null); setMessage(null); setCandidate(null)
    try {
      const revision: McpRevisionView = await client.getDefinition(row.definitionId)
      const transport = revision.canonical.transport
      setEditor('stdio' in transport
        ? { mode: 'edit', definitionId: row.definitionId, name: revision.canonical.name, transport: 'stdio',
            command: transport.stdio.command, args: transport.stdio.args.join('\n'), url: '',
            values: wireMapToRows(transport.stdio.env), expectedVersion: revision.revision }
        : { mode: 'edit', definitionId: row.definitionId, name: revision.canonical.name, transport: 'remote',
            command: '', args: '', url: transport.remote.url,
            values: wireMapToRows(transport.remote.headers), expectedVersion: revision.revision })
    } catch (error) { setRefusal(`无法载入修订：${describe(error)}`) }
  }

  const buildDefinition = (state: EditorState): McpCanonicalDefinition =>
    state.transport === 'stdio'
      ? { name: state.name, transport: { stdio: { command: state.command, args: state.args.split('\n').filter(line => line !== ''), env: rowsToWireMap(state.values) } } }
      : { name: state.name, transport: { remote: { url: state.url, headers: rowsToWireMap(state.values) } } }

  const save = async () => {
    if (!editor) return
    setRefusal(null); setMessage(null); setProbe(null)
    try {
      const saved = await client.saveRevision({
        definitionId: editor.mode === 'edit' ? editor.definitionId : undefined,
        definition: buildDefinition(editor),
        expectedVersion: editor.expectedVersion,
        operationKey: nextOperationKey(),
      })
      setCandidate({ definitionId: saved.definitionId, revision: saved.revision, hasSecretRef: definitionHasSecretRef(buildDefinition(editor)) })
      setEditor({ ...editor, mode: 'edit', definitionId: saved.definitionId, expectedVersion: saved.revision })
      // Save alone proves nothing beyond storage: the copy stays 候选/未批准.
      setMessage(`已保存候选修订 r${saved.revision}（尚未批准，不参与选择；保存不探测、不启动）`)
      void reload()
    } catch (error) { setRefusal(`保存被拒：${describe(error)}`) }
  }

  const approve = async () => {
    if (!editor || !candidate) return
    setRefusal(null)
    try {
      await client.approveRevision({
        definitionId: candidate.definitionId, revision: candidate.revision,
        expectedVersion: editor.expectedVersion, operationKey: nextOperationKey(),
      })
      setMessage(`r${candidate.revision} 已批准：可用于选择（批准只改变可选择性，不证明可连接）`)
      setCandidate(null)
      void reload()
    } catch (error) { setRefusal(`批准被拒：${describe(error)}`) }
  }

  const runProbe = async () => {
    const definitionId = editor?.definitionId ?? null
    const revision = candidate?.revision ?? editor?.expectedVersion ?? null
    if (!definitionId || revision === null) { setRefusal('请先保存一个修订再探测'); return }
    setProbe(null); setRefusal(null)
    try {
      const facts = await client.probe({ definitionId, revision })
      setProbe({ label: `${definitionId} · r${revision}`, facts })
    } catch (error) {
      // A probe refusal keeps its typed code visible; it is never softened.
      setRefusal(`探测被拒（${error instanceof McpWireError ? error.code : '未知错误'}）：${describe(error)}`)
    }
  }

  const approvalBlockedReason = candidate && candidate.hasSecretRef && !credentials
    ? '凭据服务缺席：含 secretRef 的修订不能在此应用（批准并用于选择已禁用，不造内部 vault）'
    : null

  return <div className="mcp-settings" data-testid="mcp-settings">
    <header className="mcp-settings-head">
      <h3>MCP 服务器定义</h3>
      <div>
        <button type="button" onClick={reload}>刷新</button>
        <button type="button" onClick={() => {
          setEditor({ mode: 'new', name: '', transport: 'stdio', command: '', args: '', url: '', values: [], expectedVersion: 0 })
          setCandidate(null); setProbe(null); setRefusal(null); setMessage(null)
        }}>新增定义</button>
      </div>
    </header>
    {listError && <p role="alert" className="mcp-error">定义服务不可用：{listError}（不会显示猜测数据）</p>}
    {!listError && rows && rows.length === 0 && !editor && <p className="mcp-empty">尚无 MCP 定义。</p>}
    {rows && rows.length > 0 && <table className="mcp-def-list">
      <thead><tr><th>定义名</th><th>Transport</th><th>批准修订</th><th>来源</th><th>上次探测</th><th aria-label="操作"/></tr></thead>
      <tbody>
        {rows.map(row => <tr key={row.definitionId} data-definition-id={row.definitionId}>
          <td>{row.name}{row.archived && '（已归档）'}</td>
          <td>{row.transport}</td>
          <td>{row.approvedRevision === null ? '未批准' : `r${row.approvedRevision} 已批准`}</td>
          <td>{row.source ?? '本地'}</td>
          <td>{probeColumn(row)}</td>
          <td><button type="button" onClick={() => void openEditor(row)}>编辑</button></td>
        </tr>)}
      </tbody>
    </table>}
    {editor && <section className="mcp-editor" data-testid="mcp-editor">
      <h4>{editor.mode === 'new' ? '新增定义' : `编辑 ${editor.definitionId}`}</h4>
      <label>名称 <input value={editor.name} onChange={e => setEditor({ ...editor, name: e.target.value })} placeholder="小写 slug"/></label>
      <label>Transport
        <select value={editor.transport} onChange={e => setEditor({ ...editor, transport: e.target.value === 'remote' ? 'remote' : 'stdio' })}>
          <option value="stdio">stdio</option><option value="remote">remote</option>
        </select>
      </label>
      {editor.transport === 'stdio'
        ? <>
          <label>command <input value={editor.command} onChange={e => setEditor({ ...editor, command: e.target.value })} placeholder="/绝对路径"/></label>
          <label>args（每行一个） <textarea value={editor.args} onChange={e => setEditor({ ...editor, args: e.target.value })}/></label>
          <ValueRowsEditor editor={editor} setEditor={setEditor} fieldLabel="env" credentials={credentials} credentialsList={credentialsList}/>
        </>
        : <>
          <label>url <input value={editor.url} onChange={e => setEditor({ ...editor, url: e.target.value })} placeholder="https:// 或 http://127.0.0.1/…"/></label>
          <ValueRowsEditor editor={editor} setEditor={setEditor} fieldLabel="headers" credentials={credentials} credentialsList={credentialsList}/>
        </>}
      <div className="mcp-editor-actions">
        <button type="button" data-testid="mcp-save" onClick={() => void save()}>保存候选修订</button>
        <button type="button" data-testid="mcp-approve" disabled={!candidate || approvalBlockedReason !== null}
          title={approvalBlockedReason ?? '批准该候选修订用于选择'} onClick={() => void approve()}>批准并用于选择</button>
        <button type="button" data-testid="mcp-probe" onClick={() => void runProbe()}>有限探测（无凭据）</button>
      </div>
      {approvalBlockedReason && <p role="status" className="mcp-note" data-testid="mcp-approval-blocked">{approvalBlockedReason}</p>}
    </section>}
    {message && <p role="status" className="mcp-note" data-testid="mcp-message">{message}</p>}
    {refusal && <p role="alert" className="mcp-error" data-testid="mcp-refusal">{refusal}</p>}
    {probe && <ProbeFactsView label={probe.label} facts={probe.facts}/>}
  </div>
}

/** Strictly probe wording — the column never says 连接 for a probe fact. */
function probeColumn(row: McpDefinitionSummary) {
  const last = row.lastProbe
  if (!last) return <span data-testid={`probe-cell-${row.definitionId}`}>未探测</span>
  if (last.result === 'refused') return <span data-testid={`probe-cell-${row.definitionId}`}>探测被拒（{last.code}）· r{last.revision}</span>
  return <span data-testid={`probe-cell-${row.definitionId}`}>探测成功（无凭据，r{last.revision} · {last.at}）— 非会话连接</span>
}

function ProbeFactsView({ label, facts }: { label: string; facts: McpProbeFacts }) {
  return <section className="mcp-probe-facts" data-testid="mcp-probe-facts" role="status">
    <h5>探测结果 · {label}</h5>
    <p>探测成功（无凭据）：协议 {facts.protocolVersion}，serverInfo {facts.serverInfo.name ?? '?'}@{facts.serverInfo.version ?? '?'}。</p>
    <p className="mcp-probe-scope">凭据范围：{facts.credentialScope}
      （本次不含凭据{facts.credentialsExcluded.length ? `；排除槽位：${facts.credentialsExcluded.join('、')}` : ''}）。</p>
    <p>不证明：{facts.doesNotProve.join(' / ')}。<strong>探测成功 ≠ 会话已连接。</strong></p>
  </section>
}

function ValueRowsEditor({ editor, setEditor, fieldLabel, credentials, credentialsList }: {
  editor: EditorState
  setEditor(next: EditorState): void
  fieldLabel: string
  credentials?: CredentialProvider
  credentialsList: readonly CredentialReference[] | null
}) {
  const patch = (values: ValueRow[]) => setEditor({ ...editor, values })
  return <fieldset className="mcp-value-rows">
    <legend>{fieldLabel}（literal 或 secretRef）</legend>
    {editor.values.map((row, index) => <div key={index} className="mcp-value-row" data-value-kind={row.kind}>
      <input aria-label={`${fieldLabel} 键`} value={row.key} onChange={e => patch(editor.values.map((item, i) => i === index ? { ...item, key: e.target.value } : item))}/>
      <select aria-label={`${fieldLabel} 值类型`} value={row.kind}
        onChange={e => patch(editor.values.map((item, i) => i === index ? { ...item, kind: e.target.value === 'secretRef' ? 'secretRef' : 'literal' } : item))}>
        <option value="literal">literal</option><option value="secretRef">secretRef</option>
      </select>
      {row.kind === 'literal'
        ? <input aria-label={`${fieldLabel} 值`} value={row.value} onChange={e => patch(editor.values.map((item, i) => i === index ? { ...item, value: e.target.value } : item))}/>
        : credentials
          ? <select aria-label={`${fieldLabel} 凭据引用`} value={row.value}
              onChange={e => patch(editor.values.map((item, i) => i === index ? { ...item, value: e.target.value } : item))}>
            <option value="">（选择凭据）</option>
            {(credentialsList ?? []).map(credential => <option key={credential.credentialId} value={credential.credentialId}>{credential.label}</option>)}
          </select>
          : <input aria-label={`${fieldLabel} 凭据引用`} value={row.value} readOnly disabled title="凭据服务缺席：secretRef 只读"/>}
      <button type="button" aria-label="删除条目" onClick={() => patch(editor.values.filter((_, i) => i !== index))}>×</button>
    </div>)}
    <div>
      <button type="button" onClick={() => patch([...editor.values, { key: '', kind: 'literal', value: '' }])}>+ literal 条目</button>
      <button type="button" disabled={!credentials} title={credentials ? undefined : '凭据服务缺席：不能新增 secretRef 条目'}
        onClick={() => patch([...editor.values, { key: '', kind: 'secretRef', value: '' }])}>+ secretRef 条目</button>
      {!credentials && <span className="mcp-note">凭据服务缺席：secretRef 字段只读，且此修订不能应用。</span>}
    </div>
  </fieldset>
}

function describe(error: unknown): string {
  if (error instanceof McpWireError) return `${error.code}: ${error.message}`
  return error instanceof Error ? error.message : String(error)
}
