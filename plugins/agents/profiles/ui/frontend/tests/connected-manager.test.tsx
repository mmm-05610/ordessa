// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type {
  AgentProfileCatalogClient,
  AgentProfileCatalogEntry,
  AgentProfileCatalogOutcome,
  AgentProfileManifest,
  ProfileRef,
} from '@extensions/ordessa.profile-api/contract.js'
import { ConnectedProfileManager } from '../src/connected-manager'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const roots: Root[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount())
  document.body.replaceChildren()
})

const ref: ProfileRef = {
  environmentNamespace: 'local', profileId: 'profile-a', manifestRevision: 2,
  contentDigest: `sha256:${'a'.repeat(64)}`,
}
const entry: AgentProfileCatalogEntry = {
  profileId: ref.profileId, catalogRevision: 4, displayName: 'Profile A', archivedAt: null,
  currentManifestRef: ref,
}
const ok = <T,>(value: T): AgentProfileCatalogOutcome<T> => ({ kind: 'ok', value })

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(accept => { resolve = accept })
  return { promise, resolve }
}

async function mount(client: AgentProfileCatalogClient) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => root.render(<ConnectedProfileManager client={client} />))
  return container
}

it('shows a true empty directory separately from unavailable, refused, and unknown', async () => {
  const emptyClient: AgentProfileCatalogClient = {
    capabilities: vi.fn(), list: vi.fn(async () => ok<readonly AgentProfileCatalogEntry[]>([])),
    readEntry: vi.fn(), read: vi.fn(),
  }
  const empty = await mount(emptyClient)
  await vi.waitFor(() => expect(empty.textContent).toContain('核心目录当前没有可列出的 Profile'))
  expect(empty.textContent).not.toContain('只读目录不可用')

  for (const [kind, reason, expected] of [
    ['unavailable', 'port absent', 'Profile 只读目录不可用：port absent'],
    ['refused', 'policy refused', '核心拒绝了只读请求：policy refused'],
    ['unknown', 'answer lost', '读取结果未知：answer lost'],
  ] as const) {
    const client: AgentProfileCatalogClient = {
      capabilities: vi.fn(), list: vi.fn(async () => ({ kind, reason })),
      readEntry: vi.fn(), read: vi.fn(),
    }
    const view = await mount(client)
    await vi.waitFor(() => expect(view.textContent).toContain(expected))
    expect(client.read).not.toHaveBeenCalled()
  }
})

it('reads the exact catalog ref and displays only a matching manifest', async () => {
  const manifest: AgentProfileManifest = { ref, content: { model: 'm1', enabled: true } }
  const client: AgentProfileCatalogClient = {
    capabilities: vi.fn(), list: vi.fn(async () => ok<readonly AgentProfileCatalogEntry[]>([entry])),
    readEntry: vi.fn(), read: vi.fn(async requested => ok({ ...manifest, ref: requested })),
  }
  const view = await mount(client)
  const row = await vi.waitFor(() => {
    const found = [...view.querySelectorAll('button')].find(button => button.textContent?.includes('Profile A'))
    expect(found).toBeDefined()
    return found!
  })
  await act(async () => { row.click(); await Promise.resolve() })
  expect(client.read).toHaveBeenCalledWith(ref)
  await vi.waitFor(() => expect(view.querySelector('pre')?.textContent).toContain('"model": "m1"'))

  const mismatchClient: AgentProfileCatalogClient = {
    ...client,
    read: vi.fn(async () => ok({ ...manifest, ref: { ...ref, manifestRevision: 9 } })),
  }
  const mismatch = await mount(mismatchClient)
  const mismatchRow = await vi.waitFor(() => {
    const found = [...mismatch.querySelectorAll('button')].find(button => button.textContent?.includes('Profile A'))
    expect(found).toBeDefined()
    return found!
  })
  await act(async () => { mismatchRow.click(); await Promise.resolve() })
  await vi.waitFor(() => expect(mismatch.textContent).toContain('ProfileRef 与请求不一致'))
  expect(mismatch.querySelector('pre')).toBeNull()
})

it('keeps refused and unknown manifest reads distinct and never renders a failed body', async () => {
  for (const [kind, reason, expected] of [
    ['refused', 'read policy', '核心拒绝了只读请求：read policy'],
    ['unknown', 'read reply lost', '读取结果未知：read reply lost'],
  ] as const) {
    const client: AgentProfileCatalogClient = {
      capabilities: vi.fn(), list: vi.fn(async () => ok<readonly AgentProfileCatalogEntry[]>([entry])),
      readEntry: vi.fn(), read: vi.fn(async () => ({ kind, reason })),
    }
    const view = await mount(client)
    const row = await vi.waitFor(() => {
      const found = [...view.querySelectorAll('button')].find(button => button.textContent?.includes('Profile A'))
      expect(found).toBeDefined()
      return found!
    })
    await act(async () => { row.click(); await Promise.resolve() })
    await vi.waitFor(() => expect(view.textContent).toContain(expected))
    expect(view.querySelector('pre')).toBeNull()
  }
})

it('ignores a late manifest reply after a newer catalog request wins', async () => {
  const lateRead = deferred<AgentProfileCatalogOutcome<AgentProfileManifest>>()
  const newerEntry = { ...entry, profileId: 'profile-b', displayName: 'Profile B',
    currentManifestRef: { ...ref, profileId: 'profile-b' } }
  const client: AgentProfileCatalogClient = {
    capabilities: vi.fn(),
    list: vi.fn()
      .mockImplementationOnce(async () => ok<readonly AgentProfileCatalogEntry[]>([newerEntry]))
      .mockImplementationOnce(async () => ok<readonly AgentProfileCatalogEntry[]>([])),
    readEntry: vi.fn(), read: vi.fn(() => lateRead.promise),
  }
  const view = await mount(client)
  const refresh = [...view.querySelectorAll('button')].find(button => button.textContent === '刷新')!
  await vi.waitFor(() => expect(view.textContent).toContain('Profile B'))

  const row = [...view.querySelectorAll('button')].find(button => button.textContent?.includes('Profile B'))!
  await act(async () => { row.click(); await Promise.resolve() })
  expect(client.read).toHaveBeenCalledWith(newerEntry.currentManifestRef)
  await act(async () => { refresh.click(); await Promise.resolve() })
  await vi.waitFor(() => expect(view.textContent).toContain('核心目录当前没有可列出的 Profile'))
  await act(async () => {
    lateRead.resolve(ok({ ref: newerEntry.currentManifestRef, content: { model: 'stale' } }))
    await Promise.resolve()
  })
  expect(view.querySelector('pre')).toBeNull()
  expect(view.textContent).not.toContain('stale')
  expect(view.textContent).toContain('核心目录当前没有可列出的 Profile')
})
