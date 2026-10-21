import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/profile_vocabulary.mjs"

const profile = {
    id: "claude",
    label: "Claude Code",
    // Uses the official ACP adapter for the Claude Agent SDK. The adapter speaks ACP JSON-RPC
    // over stdio and wraps @anthropic-ai/claude-agent-sdk under the hood. The user must have
    // run `claude login` or set ANTHROPIC_API_KEY before starting the bridge.
    // Requires Node 22+ (same as the PI adapter it mirrors).
    command: process.platform === "win32" ? "npx.cmd" : "npx",
    // Pinned to avoid the `notarget` scenario that PI hit. Like PI, install the scoped package
    // explicitly and invoke its published binary instead of relying on npx package-spec inference.
    // 0.63.0 embeds Claude Agent SDK 0.3.220, whose Claude Code core rejects newer advertised
    // models such as Fable 5.1 at prompt time. 0.75.1 embeds 0.3.257 and retains the adapter's
    // session-load fixes while keeping the same ACP executable contract.
    args: ["--yes", "--package=@agentclientprotocol/claude-agent-acp@0.75.1", "claude-agent-acp"],
    adapterCommand: "claude-agent-acp",
    permissionMode: "allow",
    preserveListedTimestamps: true,
    reloadOnHistoryRefresh: false,
    // The current adapter exposes model/mode but no low/medium/high reasoning-effort selector.
    // Keep this empty rather than fabricating OpenCode-style variants.
    modelVariantConfigIDs: [],
    capabilities: {
      ...COMMON_CAPABILITIES,
      // The adapter advertises a `model` config option like OMP and PI do; its values are bare ids
      // rather than `provider/model`, which is handled where the response is built.
      models: true,
      todos: true,
      commands: false,
      actions: false,
      sessionRename: true,
      sessionDelete: true
    }
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_claude.json", import.meta.url), "utf8")) }

export function launchProvenance() { return null }
