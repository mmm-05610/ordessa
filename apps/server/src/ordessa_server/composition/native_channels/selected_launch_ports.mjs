import { launchDeclaration as p9, launchProvenance as v9 } from "../../../../../../plugins/harness/grok-build/src/ordessa_harness_grok_build/acp/launch_grok_build.mjs"
/** Host explicit public-port selection; catalog bytes are supplied by the Python capture. */
import { launchDeclaration as p0, launchProvenance as v0 } from "../../../../../../plugins/harness/opencode/src/ordessa_harness_opencode/acp/launch_omp.mjs"
import { launchDeclaration as p2, launchProvenance as v2 } from "../../../../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/launch_claude.mjs"
import { launchDeclaration as p3, launchProvenance as v3 } from "../../../../../../plugins/harness/codex/src/ordessa_harness_codex/acp/launch_codex.mjs"
import { launchDeclaration as p4, launchProvenance as v4 } from "../../../../../../plugins/harness/hermes/src/ordessa_harness_hermes/acp/launch_hermes.mjs"
import { launchDeclaration as p5, launchProvenance as v5 } from "../../../../../../plugins/harness/dsh/src/ordessa_harness_dsh/acp/launch_dsh.mjs"
import { launchDeclaration as p6, launchProvenance as v6 } from "../../../../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/launch_claude_code.mjs"
import { launchDeclaration as p7, launchProvenance as v7 } from "../../../../../../plugins/harness/kilo/src/ordessa_harness_kilo/acp/launch_kilo.mjs"
import { launchDeclaration as p8, launchProvenance as v8 } from "../../../../../../plugins/harness/qwen/src/ordessa_harness_qwen/acp/launch_qwen.mjs"

// The former Pi bridge declaration selected the upstream npx launch route.
// Pi's new public Unit preparation is not yet bound by this app composition,
// so keep its registry identity visible while making this route unavailable.
// There is deliberately no legacy command, variant, extension or fallback.
const p1 = () => Object.freeze({
  id: "pi",
  origin: "upstream",
  profile: Object.freeze({ id: "pi", label: "PI", capabilities: Object.freeze({}) }),
  managed: null,
  legacy: null,
  variants: Object.freeze({}),
  allowsPythonPath: false,
  pythonRoute: null,
  nativeRoute: false,
  nativeExtension: null,
  profileExtension: null,
  modelAliases: Object.freeze({}),
  unavailableReason: "PI_PUBLIC_UNIT_LAUNCH_PORT_UNBOUND",
})
const v1 = () => null

export const selectedLaunchPorts = Object.freeze([p0,p1,p2,p3,p4,p5,p6,p7,p8,p9])

export const selectedLaunchProvenancePorts = Object.freeze([v0,v1,v2,v3,v4,v5,v6,v7,v8,v9])
