import { expect, it } from 'vitest'
import { profileFacetEditorKey } from './facet-editor-key'

it('shares one C7 identity per facet and keeps independent facets separate', () => {
  expect(profileFacetEditorKey('model')).toBe(profileFacetEditorKey('model'))
  expect(profileFacetEditorKey('skills')).not.toBe(profileFacetEditorKey('model'))
  expect(profileFacetEditorKey('model').major).toBe(1)
  expect(() => profileFacetEditorKey(' ')).toThrow('facetId')
})
