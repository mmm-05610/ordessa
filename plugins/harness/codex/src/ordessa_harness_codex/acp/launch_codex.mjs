import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/transport/profile_vocabulary.mjs"
import { createCodexHistoryLoader } from "./vendor/codex-session-history.js"
const profile = {
    id: "codex",
    label: "Codex CLI",
    // Uses the official ACP adapter for the OpenAI Codex CLI. The adapter speaks ACP JSON-RPC
    // over stdio and embeds @openai/codex, so no separate Codex installation is needed. The
    // user must have run `codex login` (ChatGPT account) or set an OpenAI API key first.
    // Requires Node 22+ (same as the PI and Claude adapters it mirrors).
    command: process.platform === "win32" ? "npx.cmd" : "npx",
    // Pinned to avoid the `notarget` scenario that PI hit. Like PI, install the scoped package
    // explicitly and invoke its published binary instead of relying on npx package-spec inference.
    args: ["--yes", "--package=@agentclientprotocol/codex-acp@1.1.14", "codex-acp"],
    adapterCommand: "codex-acp",
    permissionMode: "allow",
    // The adapter offers `api-key` before `chat-gpt`; the former demands CODEX_API_KEY or
    // OPENAI_API_KEY, while a `codex login` leaves ChatGPT credentials the `chat-gpt` method
    // reads from disk. Prefer the login, exactly like the generic default already avoids
    // env-var methods for the other harnesses.
    authMethod: "chat-gpt",
    // Codex holds a single-writer lock for as long as a client keeps a thread open, so a session the
    // desktop app is showing cannot be loaded over ACP at all. Its rollout file can, which is what
    // lets those sessions be read here. `messages` already forces a reload for every session this
    // bridge does not own, so a conversation still running in Codex keeps updating without asking
    // for the replay that the sessions we do own would otherwise repeat on each refresh.
    historyLoader: createCodexHistoryLoader(),
    preserveListedTimestamps: true,
    reloadOnHistoryRefresh: false,
    // The official adapter exposes reasoning effort independently from model selection.
    modelVariantConfigIDs: ["reasoning_effort", "reasoningEffort"],
    capabilities: {
      ...COMMON_CAPABILITIES,
      // The adapter advertises model ids as bare ids rather than `provider/model`, which is
      // handled where the response is built. Slash commands and plan updates arrive through
      // the same notifications OMP emits, so commands and todos reflect the actual wire data.
      models: true,
      todos: true,
      commands: true,
      actions: false,
      sessionRename: true,
      sessionDelete: true
    }
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_codex.json", import.meta.url), "utf8")) }

export function launchProvenance() { return new URL("./vendor/", import.meta.url) }
