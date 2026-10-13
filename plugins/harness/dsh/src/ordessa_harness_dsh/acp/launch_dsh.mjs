import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/transport/profile_vocabulary.mjs"

const profile = {
    id: "dsh",
    label: "DeepSeek dsh",
    command: process.platform === "win32" ? "dsh.cmd" : "dsh",
    args: ["--profile", "acp"],
    permissionMode: "deny",
    promptSettleMs: ACP_PROMPT_SETTLE_MS,
    modelVariantConfigIDs: [],
    capabilities: {
      ...COMMON_ACP_CAPABILITIES,
      // The ACP surface advertises a `model` config option over the
      // `deepseek-official` route (vendor protocol contract); nothing beyond
      // it (todos/commands/actions/rename/delete) is documented, so it stays
      // false until the running adapter advertises it.
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

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_dsh.json", import.meta.url), "utf8")) }

export function launchProvenance() { return null }
