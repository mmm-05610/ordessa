import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/transport/profile_vocabulary.mjs"

const profile = {
    id: "grok-build",
    label: "Grok Build",
    command: process.platform === "win32" ? "grok.exe" : "grok",
    args: ["agent", "stdio"],
    adapterCommand: process.platform === "win32" ? "grok.exe" : "grok",
    permissionMode: "deny",
    promptSettleMs: ACP_PROMPT_SETTLE_MS,
    modelVariantConfigIDs: [],
    capabilities: {
      ...COMMON_ACP_CAPABILITIES,
      // 模型配置面无文档证据（与 dsh 的 `deepseek-official` 路由不同），
      // 未观测即 false。
      models: false,
      todos: false,
      commands: false,
      actions: false,
      sessionRename: false,
      sessionDelete: false,
    },
    // ACP 重开路径无文档证据（无 session/load|resume）；同 Hermes/dsh：转写是
    // 实时 ACP 流，resume 语义待门观测，native journal 回放不宣称。
    historyLoader: undefined,
    journalPageWhileOwned: false,
    reloadOnHistoryRefresh: false,
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_grok_build.json", import.meta.url), "utf8")) }

export function launchProvenance() { return null }
