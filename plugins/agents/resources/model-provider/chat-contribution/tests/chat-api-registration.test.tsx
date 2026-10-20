// @vitest-environment jsdom
// Registration proof against the real public Chat API and the shipped key.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  ChatContributionsToken,
  createChatContributions,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  CANONICAL_MODEL_SELECTOR_ID as MODEL_SELECTOR_ID,
  CanonicalModelSelectorKey as ModelSelectorKey,
  registerCanonicalModelSelector as registerModelSelector,
} from '../src/canonical-selector'

const TOKEN_NAME = 'ordessa.chat.contributions.v1' as const

describe('model selector on the real chat contributions API', () => {
  it('uses the published token identity', () => {
    expect(ChatContributionsToken.name ?? String(ChatContributionsToken)).toContain(TOKEN_NAME)
  })

  it('registers on the published composer slot and is observable by slot', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    const disposable = registerModelSelector(chat, scope)
    const view = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    expect(view).toHaveLength(1)
    expect(view[0].id).toBe(MODEL_SELECTOR_ID)
    expect(view[0].keyId).toBe(ModelSelectorKey.id)
    expect(view[0].keyMajor).toBe(1)
    disposable.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
  })

  it('projects the session location for the composer context', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    registerModelSelector(chat, scope)
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    const context = {
      slot: 'composer.toolbar' as const,
      location: {
        kind: 'session', connectionId: 'conn-1', serverInstanceId: 'srv-1',
        sessionId: 's-9', harnessId: 'pi', contextRevision: 0,
      },
      connection: { status: 'connected' },
    } as const
    const projection = view.project?.(context)
    expect(projection).toEqual({
      hidden: false,
      props: { location: context.location },
    })
  })

  it('scope close revokes exactly this registration (absence comparison)', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    registerModelSelector(chat, scope)
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(1)
    void scope.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
  })

  it('the real registry refuses a duplicate id instead of last-write-wins', () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    registerModelSelector(chat, scope)
    expect(() => registerModelSelector(chat, scope))
      .toThrow(/duplicate/i)
  })
})
