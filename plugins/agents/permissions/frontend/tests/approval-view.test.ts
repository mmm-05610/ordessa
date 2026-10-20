// Masked view model: only backend-approved display fields survive decoding.
import { describe, expect, it } from 'vitest'
import { decodeApprovalPayload, mapNativeReceipt } from '../src/contract'

const validPayload = {
  approvalId: 'approval_abc', sessionId: 's1', executionId: 'e1', nativeRequestId: 'native-1',
  requestId: 'op-key-1', version: 1, state: 'open', decision: null, scope: null,
  receipt: null,
  display: {
    operationCategory: '写入文件', targetSummary: '<目标已脱敏>',
    policySource: 'Profile 意图', selectableScopes: [{ kind: 'once' }],
  },
  refusal: null,
  // Fields a compromised producer might append; they must never survive:
  toolArguments: '{"path":"/etc/shadow","cmd":"rm -rf"}',
  apiKey: 'sk-live-secret',
  rawCommand: 'curl evil',
}

describe('decodeApprovalPayload (FR-09 masking, C1 view model)', () => {
  it('keeps only the whitelisted masked display fields and drops every other key', () => {
    const view = decodeApprovalPayload(validPayload)
    expect(view).not.toBeNull()
    const text = JSON.stringify(view)
    expect(text).not.toContain('rm -rf')
    expect(text).not.toContain('sk-live-secret')
    expect(text).not.toContain('curl evil')
    expect(text).not.toContain('toolArguments')
    expect(view?.display.operationCategory).toBe('写入文件')
    expect(view?.display.selectableScopes).toEqual([{ kind: 'once' }])
  })

  it('a malformed payload decodes to null instead of throwing or executing', () => {
    expect(decodeApprovalPayload(null)).toBeNull()
    expect(decodeApprovalPayload({ ...validPayload, approvalId: 42 })).toBeNull()
    expect(decodeApprovalPayload({ ...validPayload, state: 'pending' })).toBeNull()
    expect(decodeApprovalPayload({ ...validPayload, display: { ...validPayload.display, policySource: '' } })).toBeNull()
    expect(decodeApprovalPayload({ ...validPayload, version: 'one' })).toBeNull()
  })

  it('a confirmed receipt without an observation time is never trusted as confirmed', () => {
    const receipt = mapNativeReceipt({ nativeRequestId: 'n', approvalId: 'a', confirmed: true, observedAt: null })
    expect(receipt).toEqual({ kind: 'unknown' })
    expect(mapNativeReceipt(null)).toEqual({ kind: 'unknown' })
    expect(mapNativeReceipt({ nativeRequestId: 'n', approvalId: 'a', confirmed: false, observedAt: null }))
      .toEqual({ kind: 'unknown' })
    expect(mapNativeReceipt({ nativeRequestId: 'n', approvalId: 'a', confirmed: true, observedAt: '2026-01-01T00:00:00Z' }))
      .toEqual({ kind: 'confirmed', observedAt: '2026-01-01T00:00:00Z' })
  })
})
