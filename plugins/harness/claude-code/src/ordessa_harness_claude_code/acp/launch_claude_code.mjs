import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/profile_vocabulary.mjs"

const profile = {
    id: "claude-code",
    label: "Claude Code",
    command: process.platform === "win32" ? "claude-agent-acp.cmd" : "claude-agent-acp",
    args: [],
    adapterCommand: process.platform === "win32" ? "claude-agent-acp.cmd" : "claude-agent-acp",
    permissionMode: "deny",
    promptSettleMs: ACP_PROMPT_SETTLE_MS,
    modelVariantConfigIDs: [],
    capabilities: {
      ...COMMON_ACP_CAPABILITIES,
      models: true,
      todos: false,
      commands: false,
      actions: false,
      sessionRename: false,
      sessionDelete: false,
    },
    historyLoader: undefined,
    journalPageWhileOwned: false,
    reloadOnHistoryRefresh: false,
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_claude_code.json", import.meta.url), "utf8")) }

export function launchProvenance() { return null }
