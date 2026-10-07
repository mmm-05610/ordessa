import { defineUiComponent, type UiComponentKey } from '@ordessa/ui-components/api'
import type { FacetEditorProps, ItemDescriptor } from './contract'

/** Domain-owned interface, consumed through C7 rather than sibling UI imports. */
export interface ProfileFacetEditorProps extends FacetEditorProps {
  readonly facetId: string
  readonly schemaVersion: string
  readonly itemDescriptors: readonly ItemDescriptor[]
}

const keys = new Map<string, UiComponentKey<ProfileFacetEditorProps>>()
export function profileFacetEditorKey(facetId: string): UiComponentKey<ProfileFacetEditorProps> {
  if (!facetId.trim()) throw new TypeError('facetId is required')
  let key = keys.get(facetId)
  if (!key) {
    key = defineUiComponent<ProfileFacetEditorProps>(`ordessa.profile.editor:${facetId}`, 1)
    keys.set(facetId, key)
  }
  return key
}
