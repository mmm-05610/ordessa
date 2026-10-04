import type { AgentSubmissionBinding, FrontendSubmissionCapture, SubmissionConditions } from '@extensions/ordessa.agent-contracts/contract.js'
import type { ChatLocation, ChatSessionGateway, ChatSubmissionResult, ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'

export interface ReliableChatSubmission {
  observe(location: ChatLocation): Promise<void>
  /** Capture synchronously at the user action, before contribution guards await. */
  capture(snapshot: ChatSubmissionSnapshot): ChatSessionGateway
}

/** Chat translates its immutable input into Agent's domain journal. Configuration,
 * durable identity, dispatch claims and recovery remain owned by Agent. */
export function createReliableChatSubmission(configuration: {
  captureSubmissionBinding(location: ChatLocation): AgentSubmissionBinding
  captureSubmissionConditions(location: ChatLocation): SubmissionConditions
  forLocation(location: ChatLocation): Promise<unknown>
}, client: {
  submit(capture: FrontendSubmissionCapture): Promise<ChatSubmissionResult>
}): ReliableChatSubmission {
  return {
    async observe(location) { await configuration.forLocation(location) },
    capture(snapshot) {
      let capture: FrontendSubmissionCapture
      try {
        const binding = configuration.captureSubmissionBinding(snapshot.target)
        const conditions = configuration.captureSubmissionConditions(snapshot.target)
        capture = Object.freeze({
          key: Object.freeze({ namespace: binding.namespace, principalScope: binding.principalScope,
            requestId: snapshot.submissionId }),
          target: binding.target, guarantee: 'reliable', generation: binding.generation,
          binding: Object.freeze({ target: binding.target, generation: binding.generation,
            expectedConditions: conditions }),
          inputSchema: binding.schema, submissionMode: binding.mode,
          draft: Object.freeze({ draftId: snapshot.draftId, draftRevision: snapshot.draftRevision,
            text: snapshot.text, attachmentIds: Object.freeze([...snapshot.attachmentIds]),
            attachmentRefs: Object.freeze([...(snapshot.attachmentRefs ?? [])]) }),
          configOperationIds: Object.freeze([...binding.configOperationIds]),
        })
      } catch (cause) {
        const reason = cause instanceof Error ? cause.message : String(cause)
        return { async submit() { return { status: 'refused', reason } } }
      }
      return { async submit() { return client.submit(capture) } }
    },
  }
}
