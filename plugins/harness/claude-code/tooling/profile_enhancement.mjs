import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { enhanceSource as compile, enhanceStaging as stage, templateResources } from "../../../../tooling/generation/harness_native_profile.mjs"
const root = fileURLToPath(new URL("../src/ordessa_harness_claude_code/acp/profile", import.meta.url))
const artifact = JSON.parse(readFileSync(new URL("../src/ordessa_harness_claude_code/acp/launch_claude_code.json",import.meta.url),"utf8"))
const strategy = Object.freeze({
  artifactContextDeclaration: fileURLToPath(new URL("./template_artifact_context.json", import.meta.url)),
  ownerId: "claude-code", pin: Object.freeze({"file": "acp-agent.js", "digest": artifact.nativeExtension.source}),
  getExpression: "agent",
  startAnchor: "export function runAcp(logger) {",
  promptExpression: "runPromptWithCancellation(agent, ctx.params, ctx.signal)",
  providerMethods: Object.freeze({"set": "unstable_setProvider", "disable": "unstable_disableProvider"}),
  imported: "import { claudeProviderAuthToken } from './ordessa-claude-auth.mjs';\nimport { providerModelCandidate, retainAcceptedProviderModel } from './ordessa-claude-provider-model.mjs';\n",
  managedAccountScope: false,
  patch(source, once) {
    source = once(source, '        if (!validValue) {\n            throw new Error(`Invalid value for config option ${params.configId}: ${params.value}`);',
      '        let ordessaProviderModel = false;\n        if (!validValue && params.configId === MODEL_CONFIG_ID) {\n            validValue = providerModelCandidate(this.providerConfig, session, params.value);\n            ordessaProviderModel = !!validValue;\n        }\n        if (!validValue) {\n            throw new Error(`Invalid value for config option ${params.configId}: ${params.value}`);')
    source = once(source, '            await this.sessions[params.sessionId].query.setModel(resolvedValue);',
      '            await this.sessions[params.sessionId].query.setModel(resolvedValue);\n            if (ordessaProviderModel) retainAcceptedProviderModel(session, resolvedValue);')
    source = once(source, '                providerCacheKey,',
      '                providerCacheKey,\n                ordessaProviderRoute: { apiType: resolvedProvider?.apiType ?? null, baseUrl: resolvedProvider?.baseUrl ?? null },')
    source = once(source, 'ANTHROPIC_AUTH_TOKEN: "acp-proxy", // Bypass local Claude login checks',
      'ANTHROPIC_AUTH_TOKEN: claudeProviderAuthToken(config.headers), // Private provider credential, not login placeholder')
  
    return source
  },
  resources: Object.freeze({
    "ordessa-profile.mjs": path.join(root, "entry.mjs"),
    "ordessa-native-profile.mjs": path.join(root, "bridge.mjs"),
    "ordessa-native-configuration-query.mjs": path.join(root, "configuration-query.mjs"),
    "ordessa-native-routing.mjs": path.join(root, "routing.mjs"),
    "ordessa-native-strategy.mjs": path.join(root, "strategy.mjs"),
    "ordessa-claude-auth.mjs": path.join(root, "claude-auth.mjs"),
    "ordessa-claude-provider-model.mjs": path.join(root, "claude-provider-model.mjs"),
  })
})
export function enhanceSource(source) { return compile(source,strategy) }
export function enhanceStaging(dist) { return stage(dist,strategy) }

export function enhancementTemplateResources() { return templateResources(strategy) }

export function templateArtifactContextDeclaration() { return strategy.artifactContextDeclaration }
