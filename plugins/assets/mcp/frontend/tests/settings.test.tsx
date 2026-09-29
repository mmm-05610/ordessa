// Settings section proofs (ux.md「Settings 的 MCP 区」, V08 rows: 探测文案、
// literal/secretRef 分流、Credential 缺席、批准独立动作、探测范围声明).

import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { McpSettingsSection } from '../src/settings'
import type { CredentialProvider } from '../src/credentials'
import { createFakeWireClient, baseSummary } from './fakes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => { root.unmount() }); container.remove() })
  await act(async () => { root.render(element) })
  return container
}

const byTestId = (container: HTMLElement, id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`)
const button = (container: HTMLElement, testId: string) => byTestId(container, testId) as HTMLButtonElement
const provider: CredentialProvider = { listCredentials: async () => [{ credentialId: 'cred-1', label: '凭据一' }] }

describe('MCP settings list', () => {
  it('renders name/transport/approved revision/source and words the probe column as 探测成功（无凭据）— never a connection claim', async () => {
    const container = await mount(<McpSettingsSection client={createFakeWireClient()} />)
    const cell = byTestId(container, 'probe-cell-srv-a')
    expect(cell?.textContent).toContain('探测成功（无凭据')
    expect(cell?.textContent).toContain('非会话连接')
    expect(container.textContent).not.toMatch(/已连接|连接成功/)
    const row = container.querySelector('tr[data-definition-id="srv-a"]')!
    expect(row.textContent).toContain('stdio')
    expect(row.textContent).toContain('r1 已批准')
    expect(row.textContent).toContain('导入 · claude_desktop')
  })

  it('shows 未探测 when no probe fact exists', async () => {
    const client = createFakeWireClient()
    client.state.definitions = [{ ...baseSummary, lastProbe: null }]
    const container = await mount(<McpSettingsSection client={client} />)
    expect(byTestId(container, 'probe-cell-srv-a')?.textContent).toBe('未探测')
  })
})

describe('MCP definition editor', () => {
  it('splits literal vs secretRef inputs; with a credential provider the reference is a picker over ids only', async () => {
    const client = createFakeWireClient()
    const container = await mount(<McpSettingsSection client={client} credentials={provider} />)
    // Load the existing revision through the row editor.
    const editButton = container.querySelector<HTMLButtonElement>('tr[data-definition-id="srv-a"] button')!
    await act(async () => { editButton.click() })
    const rows = container.querySelectorAll<HTMLElement>('.mcp-value-row')
    expect(rows).toHaveLength(2)
    const secretRow = [...rows].find(row => row.dataset.valueKind === 'secretRef')!
    const literalRow = [...rows].find(row => row.dataset.valueKind === 'literal')!
    // The secret row is a <select> of credential ids — no plaintext input, and
    // the stored value shown is the reference id, never a secret.
    expect(secretRow.querySelector('select')).not.toBeNull()
    expect(secretRow.textContent).not.toContain('cred-1value')
    expect(literalRow.querySelector('input:last-of-type')).not.toBeNull()
    const options = [...secretRow.querySelectorAll('option')].map(option => option.value)
    expect(options).toContain('cred-1')
  })

  it('without the credential service secretRef fields are read-only AND approval cannot be applied', async () => {
    const client = createFakeWireClient()
    const container = await mount(<McpSettingsSection client={client} />)
    const editButton = container.querySelector<HTMLButtonElement>('tr[data-definition-id="srv-a"] button')!
    await act(async () => { editButton.click() })
    const secretRow = [...container.querySelectorAll<HTMLElement>('.mcp-value-row')].find(row => row.dataset.valueKind === 'secretRef')!
    const input = secretRow.querySelector<HTMLInputElement>('input[aria-label$="凭据引用"]')!
    expect(input.disabled).toBe(true)
    expect(byTestId(container, 'mcp-approval-blocked')).toBeNull() // nothing saved yet
    await act(async () => { button(container, 'mcp-save').click() })
    expect(byTestId(container, 'mcp-message')?.textContent).toContain('候选修订')
    expect(byTestId(container, 'mcp-message')?.textContent).toContain('尚未批准')
    expect(button(container, 'mcp-approve').disabled).toBe(true)
    expect(byTestId(container, 'mcp-approval-blocked')?.textContent).toContain('凭据服务缺席')
    expect(client.calls.some(call => call.method === 'approveRevision')).toBe(false)
  })

  it('save then 批准并用于选择 are two independent calls; approval saves nothing new', async () => {
    const client = createFakeWireClient()
    const container = await mount(<McpSettingsSection client={client} credentials={provider} />)
    const editButton = container.querySelector<HTMLButtonElement>('tr[data-definition-id="srv-a"] button')!
    await act(async () => { editButton.click() })
    await act(async () => { button(container, 'mcp-save').click() })
    expect(client.calls.filter(call => call.method === 'saveRevision')).toHaveLength(1)
    expect(client.calls.some(call => call.method === 'approveRevision')).toBe(false)
    expect(button(container, 'mcp-approve').disabled).toBe(false)
    await act(async () => { button(container, 'mcp-approve').click() })
    const approve = client.calls.find(call => call.method === 'approveRevision')!
    expect(approve.params).toMatchObject({ definitionId: 'srv-a', revision: 3 })
    expect(byTestId(container, 'mcp-message')?.textContent).toContain('可用于选择')
  })
})

describe('MCP bounded probe', () => {
  it('shows the credential-less scope declaration from the probe facts', async () => {
    const client = createFakeWireClient()
    const container = await mount(<McpSettingsSection client={client} />)
    const editButton = container.querySelector<HTMLButtonElement>('tr[data-definition-id="srv-a"] button')!
    await act(async () => { editButton.click() })
    await act(async () => { button(container, 'mcp-probe').click() })
    const facts = byTestId(container, 'mcp-probe-facts')!
    expect(facts.textContent).toContain('探测成功（无凭据）')
    expect(facts.textContent).toContain('unproven')
    expect(facts.textContent).toContain('排除槽位：env.TOKEN')
    expect(facts.textContent).toContain('不证明：tool-catalog / credential-usability / connection-lease / tool-invocability')
    expect(facts.textContent).toContain('探测成功 ≠ 会话已连接')
  })

  it('a typed probe refusal keeps its code visible', async () => {
    const client = createFakeWireClient()
    client.state.failOn.probe = 'handshake timed out'
    const container = await mount(<McpSettingsSection client={client} />)
    const editButton = container.querySelector<HTMLButtonElement>('tr[data-definition-id="srv-a"] button')!
    await act(async () => { editButton.click() })
    await act(async () => { button(container, 'mcp-probe').click() })
    expect(byTestId(container, 'mcp-refusal')?.textContent).toContain('PROBE_FAILED')
    expect(byTestId(container, 'mcp-probe-facts')).toBeNull()
  })
})
