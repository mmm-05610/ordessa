import { capturedCapabilityText } from "./captured_launch.mjs"
import { selectedLaunchPorts } from "../../src/ordessa_server/composition/native_channels/selected_launch_ports.mjs"
import { captureProfileClaims, NATIVE_CAPABILITY_TO_CANONICAL, UNMAPPED_NATIVE_CAPABILITIES } from "../../../../packages/execution/agents/src/ordessa_agents/harness/transport/profile_claims.mjs"
import { modelAliases as opencodeModelAliases } from "../../../../plugins/harness/opencode/src/ordessa_harness_opencode/acp/profile_declarations.mjs"
export { NATIVE_CAPABILITY_TO_CANONICAL, UNMAPPED_NATIVE_CAPABILITIES }
const declarations=selectedLaunchPorts.map(port=>port())
export const projection=JSON.parse(capturedCapabilityText())
export const {canonicalCapabilityClaims,capabilityDeclarations,declaredCapabilityCeiling,registeredHarnessIDs,resolveHarnessProfile}=captureProfileClaims(declarations,projection)
export const AGENTBOX_HARNESS_PROFILES=Object.freeze(Object.fromEntries(declarations.filter(value=>value.origin==="agentbox").map(value=>[value.id,value.profile])))
export const AGENTBOX_MODEL_ALIASES = Object.freeze({ ...Object.fromEntries(declarations.filter(value => value.modelAliases && Object.keys(value.modelAliases).length).map(value => [value.id, Object.freeze(value.modelAliases)])), opencode: opencodeModelAliases })
export function resolveNativeModel(id,model) { if(typeof model!=="string"||!model)return model;const fact=declarations.find(value=>value.id===id);return (fact?.modelAliases??(id==="opencode"?opencodeModelAliases:{}))[model]??model }
export function emptyCapabilityProjection() { return captureProfileClaims(declarations,null) }
