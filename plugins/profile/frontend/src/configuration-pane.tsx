import { useEffect, useRef, useState } from 'react'
import { ComponentOutlet } from '@ordessa/ui-components/react'
import type { UiBinding, UiScope } from '@ordessa/ui-components/api'
import { profileFacetEditorKey, type FacetCatalogEntry, type ProfileFacetEditorProps,
  type ProfileIdentityDto, type ProfileServiceClient, type ResolvePreviewDto } from '@extensions/ordessa.profile-api/contract.js'
import type { ProfileDraftStore } from './stores'

function FacetSlot({ ui, value }: { ui: UiScope; value: ProfileFacetEditorProps }) {
  const [binding, setBinding] = useState<UiBinding<ProfileFacetEditorProps> | null>(null)
  useEffect(() => {
    const owned = ui.bind(profileFacetEditorKey(value.facetId), { required: false })
    setBinding(owned)
    return () => owned.dispose()
  }, [ui, value.facetId])
  // A removed editor disappears; stored configuration is not deleted.
  return binding ? <ComponentOutlet binding={binding} value={value} /> : null
}

export function ProfileConfigurationPane({ client, profile, draft, ui, generation, changed, busy }: {
  client: ProfileServiceClient; profile: ProfileIdentityDto; draft: ProfileDraftStore;
  ui: UiScope; generation: number; changed: () => void; busy: boolean;
}) {
  const [data, setData] = useState<{ facets: readonly FacetCatalogEntry[]; preview: ResolvePreviewDto } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const live = useRef(false)
  const fence = useRef({ generation, busy })
  fence.current = { generation, busy }
  useEffect(() => {
    let active = true
    live.current = true
    setData(null); setError(null)
    void Promise.all([client.describeFacets(profile.harnessId), client.resolvePreview(profile.profileId)])
      .then(([facets, preview]) => {
        if (!active) return
        if (preview.profileId !== profile.profileId || preview.harnessId !== profile.harnessId
            || preview.revision !== profile.currentRevision)
          throw new Error('预设已经变更，请刷新后编辑')
        setData({ facets, preview })
      }).catch(e => { if (active) setError(String(e)) })
    return () => { active = false; live.current = false }
  }, [client, profile.profileId, profile.harnessId, profile.currentRevision, retry])
  if (error) return <div role="alert">{error}<button onClick={() => setRetry(n => n + 1)}>重试配置加载</button></div>
  if (!data) return <p role="status">读取预设配置…</p>
  return <div data-profile-configuration="">
    {data.facets.filter(f => f.applicability !== 'unsupported').map(facet => {
      const items = data.preview.items.filter(i => i.facetId === facet.facetId)
      const effective = [...items]
      for (const patch of draft.localPatches.filter(p => p.facetId === facet.facetId)) {
        const index = effective.findIndex(i => i.itemId === patch.itemId)
        if (index !== -1) effective.splice(index, 1)
        if (patch.op === 'set') effective.push({ facetId: patch.facetId, itemId: patch.itemId,
          value: patch.value, state: 'explicit', source: { kind: 'profile', revision: profile.currentRevision } })
      }
      return <FacetSlot key={facet.facetId} ui={ui} value={{
        facetId: facet.facetId, schemaVersion: facet.schemaVersion,
        target: { serverRef: profile.realm, profileId: profile.profileId, harnessId: profile.harnessId },
        revision: profile.currentRevision, draftGeneration: generation, items: effective,
        itemDescriptors: facet.itemDescriptors, validation: data.preview.conflicts.filter(v => v.facetId === facet.facetId),
        applicability: facet.applicability,
        readOnlyReason: busy ? '正在保存' : profile.archivedAt ? '已归档预设只读' : undefined,
        onPatch: patches => {
          if (!live.current || fence.current.busy || fence.current.generation !== generation || profile.archivedAt) return
          if (patches.some(p => p.facetId !== facet.facetId || !facet.itemDescriptors.some(i => i.itemId === p.itemId))) {
            setError('配置编辑器提交了越界条目'); return
          }
          for (const patch of patches) draft.edit(patch)
          changed()
        },
      }} />
    })}
    <p>保存只更新预设；不会打断当前 Agent 输出。</p>
  </div>
}
