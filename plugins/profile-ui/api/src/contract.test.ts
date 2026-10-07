/**
 * Contract behaviour tests: registration semantics, typed patches, value
 * states, and compile-time negative cases (@ts-expect-error).
 */
import { describe, expect, it } from 'vitest'
import {
  assertItemPatch,
  DelegatingProfileServiceClient,
  DuplicateContributionError,
  InMemoryProfileContributions,
  ProfileServiceError,
  UNSET,
  valueState,
} from '../src/index'
import type {
  ItemPatch,
  ProfileEditorContribution,
  ProfileSettingsContribution,
} from '../src/index'

function makeEditor(facetId: string, order = 1): ProfileEditorContribution {
  return {
    facetId,
    supportedSchemaRange: ['1.0.0', '2.0.0'],
    componentKey: `editor.${facetId}` as ProfileEditorContribution['componentKey'],
    category: 'model',
    order,
  }
}

function makeSettings(id: string, order = 1): ProfileSettingsContribution {
  return {
    id,
    facetId: 'facet',
    title: id,
    order,
    componentKey: `settings.${id}` as ProfileSettingsContribution['componentKey'],
  }
}

describe('value states (PF04)', () => {
  it('keeps the four states distinguishable', () => {
    expect(valueState(UNSET)).toBe('unset')
    expect(valueState(null)).toBe('explicit')
    expect(valueState([])).toBe('explicit')
    expect(valueState(false)).toBe('explicit')
    expect(valueState(0)).toBe('explicit')
    expect(valueState({ disabled: true })).toBe('disabled')
    expect(valueState('provider-absent' as never)).toBe('explicit')
  })

  it('UNSET is not undefined or null', () => {
    expect(UNSET).not.toBe(undefined)
    expect(UNSET).not.toBe(null)
  })
})

describe('item patches', () => {
  it('accepts set and unset patches', () => {
    const set: ItemPatch = { facetId: 'f', itemId: 'i', op: 'set', value: 0 }
    const unset: ItemPatch = { facetId: 'f', itemId: 'i', op: 'unset' }
    expect(() => { assertItemPatch(set) }).not.toThrow()
    expect(() => { assertItemPatch(unset) }).not.toThrow()
  })

  it('refuses a set without value and an unset with value', () => {
    expect(() => assertItemPatch({ facetId: 'f', itemId: 'i', op: 'set', value: undefined as never }))
      .toThrow(/requires a value/)
    const dirty = { ...{ facetId: 'f', itemId: 'i', op: 'unset' }, value: 1 }
    expect(() => assertItemPatch(dirty as ItemPatch))
      .toThrow(/must not carry/)
    expect(() => assertItemPatch({ facetId: 'f', itemId: 'i', op: 'toggle' as never }))
      .toThrow(/unknown ItemPatch op/)
  })
})

describe('in-memory contribution registry', () => {
  it('refuses duplicates and unloads on dispose', () => {
    const registry = new InMemoryProfileContributions()
    const scope = {} as never
    const forScope = registry.forScope(scope)
    const d1 = forScope.addEditor(makeEditor('f1'))
    expect(() => forScope.addEditor(makeEditor('f1'))).toThrow(DuplicateContributionError)
    d1.dispose()
    expect(registry.editorsOf(scope)).toHaveLength(0)
    const d2 = forScope.addSettingsSection(makeSettings('s1'))
    expect(() => forScope.addSettingsSection(makeSettings('s1'))).toThrow(DuplicateContributionError)
    d2.dispose()
    expect(registry.settingsOf(scope)).toHaveLength(0)
  })

  it('orders contributions and isolates scopes', () => {
    const registry = new InMemoryProfileContributions()
    const scopeA = {} as never
    const scopeB = {} as never
    registry.forScope(scopeA).addEditor(makeEditor('f2', 2))
    registry.forScope(scopeA).addEditor(makeEditor('f1', 1))
    registry.forScope(scopeB).addEditor(makeEditor('f3', 1))
    expect(registry.editorsOf(scopeA).map((e) => e.facetId)).toEqual(['f1', 'f2'])
    expect(registry.editorsOf(scopeB).map((e) => e.facetId)).toEqual(['f3'])
  })
})

describe('delegating service client', () => {
  it('routes operations to the transport and rejects fake absence', async () => {
    const calls: Array<[string, unknown]> = []
    const client = new DelegatingProfileServiceClient(async (op, payload) => {
      calls.push([op, payload])
      if (op === 'selectForSession')
        return { sessionRef: {}, pendingProfileId: 'p2', pendingSeq: 3, switchState: 'pending' }
      if (op === 'beginTurnApplication')
        throw new ProfileServiceError('APPLICATION_PORT_ABSENT', 'no port', 409)
      return {}
    })
    const selection = await client.selectForSession('k', {
      sessionRef: { realm: 'r', harnessId: 'h', nativeSessionKey: 'n', sessionUid: 'u' },
      profileId: 'p2',
    })
    expect(selection.switchState).toBe('pending')
    expect(calls[0]?.[0]).toBe('selectForSession')
    await expect(client.beginTurnApplication('k2', {
      realm: 'r', harnessId: 'h', nativeSessionKey: 'n', sessionUid: 'u',
    })).rejects.toMatchObject({ code: 'APPLICATION_PORT_ABSENT' })
  })
})

describe('compile-time negatives', () => {
  it('forbids collapsing the four value states', () => {
    // @ts-expect-error undefined is not a valid representation of UNSET
    const bad: typeof UNSET = undefined
    expect(bad).toBeUndefined()
  })

  it('forbids an unknown patch op', () => {
    const patch: ItemPatch = { facetId: 'f', itemId: 'i', op: 'set', value: 1 }
    // @ts-expect-error 'reset' is not a frontend patch op (that is a backend intent)
    const wrong: ItemPatch = { ...patch, op: 'reset' }
    expect(() => assertItemPatch(wrong)).toThrow()
  })
})
