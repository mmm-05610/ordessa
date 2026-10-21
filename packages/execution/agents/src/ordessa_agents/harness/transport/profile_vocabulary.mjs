export const COMMON_CAPABILITIES = {
  sessions: true,
  prompt: true,
  abort: true,
  streaming: true,
  agents: false,
  diff: false,
  filesystemBrowser: true,
  questions: false,
  permissions: false,
  sessionRename: false,
  sessionDelete: false
}


export const COMMON_ACP_CAPABILITIES = COMMON_CAPABILITIES
export const ACP_PROMPT_SETTLE_MS = 250
