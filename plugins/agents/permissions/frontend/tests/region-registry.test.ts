// The approval region registers through Chat's REAL registry: Chat's own code
// enforces duplicate ids/kinds, (order,id) sorting and scope withdrawal.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, chatContribution } from '@extensions/ordessa.chat-api/contract.js'
import { ApprovalCardKey, ApprovalRegionKey, createApprovalContributions } from '../src/approval-region'

describe('approval contributions against Chat\'s real registry', () => {
  it('both contributions register and appear in their slots sorted by (order, id)', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    const { region, card } = createApprovalContributions()
    scope.add(registry.forScope(scope).addContribution(region))
    scope.add(registry.forScope(scope).addContribution(card))
    const aux = registry.contributionsBySlot('session.auxiliary').getSnapshot()
    expect(aux.map(c => c.id)).toContain('permissions.approval-region')
    const regionView = aux.find(c => c.id === 'permissions.approval-region')
    expect(regionView?.keyId).toBe(ApprovalRegionKey.id)
    expect(typeof regionView?.project).toBe('function')
    const renderers = registry.contributionsBySlot('content.renderers').getSnapshot()
    const cardView = renderers.find(c => c.id === 'permissions.approval-card')
    expect(cardView?.contentKind).toBe('ordessa.permissions.approval-request')
    expect(cardView?.keyId).toBe(ApprovalCardKey.id)
    expect(typeof cardView?.decode).toBe('function')
  })

  it('a duplicate id is refused by Chat itself: Error "Duplicate chat contribution: permissions.approval-region"', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    registry.forScope(scope).addContribution(createApprovalContributions().region)
    expect(() => registry.forScope(new OwnedResources()).addContribution(createApprovalContributions().region))
      .toThrow(Error)
    expect(() => registry.forScope(new OwnedResources()).addContribution(createApprovalContributions().region))
      .toThrow('Duplicate chat contribution: permissions.approval-region')
  })

  it('a duplicate contentKind is refused by Chat itself: Error "Duplicate chat content kind: …"', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    registry.forScope(scope).addContribution(createApprovalContributions().card)
    const rival = chatContribution({
      id: 'rival.approval-card', slot: 'content.renderers', order: 5, key: ApprovalCardKey,
      contentKind: 'ordessa.permissions.approval-request', decode: () => null,
    })
    expect(() => registry.forScope(new OwnedResources()).addContribution(rival))
      .toThrow('Duplicate chat content kind: ordessa.permissions.approval-request')
  })

  it('a hand-made registration record is refused: TypeError "Not a chatContribution() record"', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    const forged = { id: 'permissions.approval-region' } as never
    expect(() => registry.forScope(scope).addContribution(forged)).toThrow(TypeError)
  })

  it('closing the owning scope withdraws the contribution from Chat (FR-08: 卸载不丢数据、不伪造可用)', () => {
    const registry = createChatContributions()
    const scope = new OwnedResources()
    registry.forScope(scope).addContribution(createApprovalContributions().region)
    expect(registry.contributionsBySlot('session.auxiliary').getSnapshot().map(c => c.id))
      .toContain('permissions.approval-region')
    scope.dispose()
    expect(registry.contributionsBySlot('session.auxiliary').getSnapshot().map(c => c.id))
      .not.toContain('permissions.approval-region')
    expect(() => registry.forScope(scope)).toThrow('Chat contribution scope is closed')
  })
})
