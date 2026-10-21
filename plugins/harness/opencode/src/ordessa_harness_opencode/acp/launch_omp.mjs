import { readFileSync } from "node:fs"
import { COMMON_CAPABILITIES, COMMON_ACP_CAPABILITIES, ACP_PROMPT_SETTLE_MS } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/profile_vocabulary.mjs"
import { createOmpHistoryLoader } from "./vendor/omp-session-history.js"
import { OMP_EXTENSION_ACTION_PROVIDERS } from "./vendor/extension-actions.js"
const profile = {
    id: "omp",
    label: "Oh My Pi",
    command: "omp",
    args: ["acp"],
    permissionMode: "allow",
    historyLoader: createOmpHistoryLoader(),
    // OMP's journal is the only place a message has a stable identity. Its ACP stream mints a new
    // `messageId` for every live message and mints new ones again on every `session/load` replay,
    // so a Session read once from each source is one conversation with two sets of ids. The journal
    // is therefore the transcript until this bridge takes the writer, and this bridge's own stream
    // is the transcript from then on - never both at once. See AcpService#journalPageWhileOwned.
    journalPageWhileOwned: false,
    // OMP stores a Session's name itself - `/rename` calls `setSessionName(title, "user")`, which
    // writes the title slot and marks it user-set so OMP's own auto-titling leaves it alone. A name
    // kept only in this bridge's snapshot was invisible in the Session index, which reads the
    // harness's lightweight listing, and gone entirely for a Session reopened from OMP.
    nativeRenameCommand: "rename",
    preferListedTitles: true,
    // A transcript that already came from the journal must not be asked for again over ACP, so an
    // owned OMP Session is opened with `session/resume` rather than the replaying `session/load`.
    // Reloading on refresh would reintroduce exactly that replay.
    reloadOnHistoryRefresh: false,
    // OMP exposes thinking as a real ACP config option. We probe only ids the running adapter
    // actually advertises; this list is a routing hint, never a source of invented variants.
    modelVariantConfigIDs: ["thinking"],
    capabilities: {
      ...COMMON_CAPABILITIES,
      models: true,
      todos: true,
      commands: true,
      actions: true,
      sessionRename: true,
      sessionDelete: true
    },
    actionProviders: OMP_EXTENSION_ACTION_PROVIDERS
  }
export function launchDeclaration() { return { profile, ...artifactDeclaration() } }

function artifactDeclaration() { return JSON.parse(readFileSync(new URL("./launch_omp.json", import.meta.url), "utf8")) }

export function launchProvenance() { return new URL("./vendor/", import.meta.url) }
