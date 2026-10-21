import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/profile_vocabulary.mjs"

const profile = {
    id: "hermes",
    label: "Hermes Agent",
    command: process.platform === "win32" ? "hermes.exe" : "hermes",
    args: ["acp"],
    adapterCommand: process.platform === "win32" ? "hermes.exe" : "hermes",
    // Approval policy is AgentBox-owned: the injected asynchronous permission
    // resolver decides, and an unanswered decision denies. `deny` is the
    // honest default for the prompt-less model-catalog connection too.
    permissionMode: "deny",
    promptSettleMs: ACP_PROMPT_SETTLE_MS,
    modelVariantConfigIDs: [],
    capabilities: {
      ...COMMON_ACP_CAPABILITIES,
      models: false,
      todos: false,
      commands: false,
      actions: false,
      sessionRename: false,
      sessionDelete: false,
    },
    // Hermes keeps its own session store. No reviewed upstream history loader
    // exists for it, so the transcript is the live ACP stream only; native
    // journal replay is explicitly not claimed.
    historyLoader: undefined,
    journalPageWhileOwned: false,
    reloadOnHistoryRefresh: false,
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_hermes.json", import.meta.url), "utf8")) }

export function launchProvenance() { return null }
