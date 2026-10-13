import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { captureTemplateArtifactContext, verifyTemplateArtifactEmission } from '../../../../tooling/generation/harness_template_context.mjs'
import { stageTemplateGraph } from "../../../../tooling/generation/harness_template_graph.mjs"
export function profileTemplateResources() { return Object.freeze({"ordessa-canonical-json.mjs":fileURLToPath(new URL("../../../../packages/infrastructure/src/ordessa_infrastructure/encoding/canonical_json.mjs",import.meta.url)),"ordessa-configuration-query.mjs":fileURLToPath(new URL("../../../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/digest.mjs",import.meta.url)),"ordessa-configuration-operation.mjs":fileURLToPath(new URL("../../../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/operation.mjs",import.meta.url)),"ordessa-profile.mjs":fileURLToPath(new URL("../src/ordessa_harness_pi/acp/profile/entry.mjs",import.meta.url)),"ordessa-profile-server.mjs":fileURLToPath(new URL("../src/ordessa_harness_pi/acp/profile/server.mjs",import.meta.url)),"ordessa-pi-configuration-query.mjs":fileURLToPath(new URL("../src/ordessa_harness_pi/acp/profile/configuration-query.mjs",import.meta.url)),"ordessa-creation.mjs":fileURLToPath(new URL("../src/ordessa_harness_pi/acp/profile/creation.mjs",import.meta.url)),"ordessa-provider-registration.mjs":fileURLToPath(new URL("../src/ordessa_harness_pi/acp/profile/provider-registration.mjs",import.meta.url))}) }
export function templateArtifactContextDeclaration() { return fileURLToPath(new URL('./template_artifact_context.json',import.meta.url)) }
export function stagePiProfile(destination) {
  const resources = profileTemplateResources()
  const captured = captureTemplateArtifactContext(templateArtifactContextDeclaration(), {resources,upstreamPackageRoot:path.resolve(destination,'..')})
  const rewrites = stageTemplateGraph(destination,resources)
  verifyTemplateArtifactEmission(path.resolve(destination),captured)
  return rewrites
}
