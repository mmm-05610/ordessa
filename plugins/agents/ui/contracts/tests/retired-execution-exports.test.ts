import { expect, it } from 'vitest'
import * as contract from '../src/contract'

it('keeps the Agent session/connection carrier without retired config or durable-submission exports', () => {
  const exports = Object.keys(contract)
  expect(exports).toContain('AgentSessionsToken')
  expect(exports).toContain('AgentClientConnectionKind')
  for (const retired of [
    'createAgentOwnerPort', 'createConfigurationProjection', 'createWireConfigurationClient',
    'createWireSubmissionClient', 'createFrontendSubmissionJournal', 'createDurableSubmissionClient',
    'createSubmissionRecoveryClient', 'AgentOwnerPort', 'ConfigSnapshotView', 'FrontendSubmissionJournal',
  ]) expect(exports, retired).not.toContain(retired)
})
