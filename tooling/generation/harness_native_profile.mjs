import { fileURLToPath } from 'node:url'
import { stageTemplateGraph } from './harness_template_graph.mjs'
import { captureTemplateArtifactContext, verifyTemplateArtifactEmission } from './harness_template_context.mjs'
import { createHash } from 'node:crypto'
import { chmodSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
function once(source, before, after) {
  if (source.split(before).length !== 2) throw new Error('Native Profile patch anchor drift')
  return source.replace(before, after)
}
export function enhanceSource(source, strategy) {
  const pin = strategy?.pin
  if (!pin || createHash('sha256').update(source).digest('hex') !== pin.digest)
    throw new Error('Native Profile upstream source digest mismatch')
  const get = strategy.getExpression
  const setup = `\nconst ordessaBridges = new WeakMap();\nfunction ordessaProfile(instance) {\n  let bridge = ordessaBridges.get(instance);\n  if (!bridge) {\n    bridge = nativeProfileBridge(instance, message => RequestError.invalidParams(undefined, message));\n    ordessaBridges.set(instance, bridge);\n  }\n  return bridge;\n}\n`
  source = once(source, strategy.startAnchor,
    setup + (strategy.startAnchor))
  source = once(source, `.onRequest(methods.agent.initialize, (ctx) => ${get}.initialize(ctx.params))`,
    `.onRequest(methods.agent.initialize, async (ctx) => { const result = await ${get}.initialize(ctx.params); return { ...result, _meta: { ...result._meta, ordessaConfiguration: { supported: true, version: 1 } } }; })`)
  source = once(source,
    `.onRequest(methods.agent.session.setConfigOption, (ctx) => ${get}.setSessionConfigOption(ctx.params))`,
    `.onRequest(methods.agent.session.setConfigOption, (ctx) => ordessaProfile(${get}).operation.withSession(ctx.params.sessionId, () => ${get}.setSessionConfigOption(ctx.params)))`)
  for (const [method, impl] of [['new', 'newSession'], ['load', 'loadSession'],
    ['resume', 'resumeSession'], ['close', 'closeSession'], ['delete', 'deleteSession']])
    source = once(source, `.onRequest(methods.agent.session.${method}, (ctx) => ${get}.${impl}(ctx.params))`,
      `.onRequest(methods.agent.session.${method}, (ctx) => ordessaProfile(${get}).${['new', 'load', 'resume'].includes(method) ? `withCreation(ctx.params, params => ${get}.${impl}(params)` : `withLifecycle(() => ${get}.${impl}(ctx.params)`}))`)
  const prompt = strategy.promptExpression
  source = once(source, `.onRequest(methods.agent.session.prompt, (ctx) => ${prompt})`,
    `.onRequest(methods.agent.session.prompt, (ctx) => ordessaProfile(${get}).operation.withSession(ctx.params.sessionId, () => ${prompt}))`)
  for (const method of ['set', 'disable']) {
    const impl = strategy.providerMethods[method]
    source = once(source, `.onRequest(methods.agent.providers.${method}, (ctx) => ${get}.${impl}(ctx.params))`,
      `.onRequest(methods.agent.providers.${method}, (ctx) => ordessaProfile(${get}).withExternalProvider(() => ${get}.${impl}(ctx.params)))`)
  }
  const registration = `.onRequest('_ordessa/session/configuration', { parse: input => ordessaProfile(${get}).parser.parse(input) }, ctx => ordessaProfile(${get}).read(ctx.params))
    .onRequest('_ordessa/channel/configuration/prepare', { parse: input => ordessaProfile(${get}).creationParser.parse(input) }, ctx => ordessaProfile(${get}).prepareCreation(ctx.params))
    .onRequest('_ordessa/channel/configuration/operation', { parse: input => ordessaProfile(${get}).creationQueryParser.parse(input) }, ctx => ordessaProfile(${get}).queryCreation(ctx.params))
    .onRequest('_ordessa/session/configuration/apply', { parse: input => ordessaProfile(${get}).operation.parseApply(input) }, ctx => ordessaProfile(${get}).apply(ctx.params))
    .onRequest('_ordessa/session/configuration/restore', { parse: input => ordessaProfile(${get}).restoration.parse(input) }, ctx => ordessaProfile(${get}).restoration.apply(ctx.params))
    .onRequest('_ordessa/session/configuration/operation', { parse: input => ordessaProfile(${get}).operation.parseQuery(input) }, ctx => ordessaProfile(${get}).queryOperation(ctx.params))
    `
  source = once(source, '.onRequest(methods.agent.session.setMode,', registration + '.onRequest(methods.agent.session.setMode,')
  source = strategy.patch(source,once)
  const imported = "import { nativeProfileBridge } from './ordessa-native-profile.mjs';\n" + strategy.imported
  source = source.startsWith('#!') ? source.replace('\n', '\n' + imported) : imported + source
  return source
}

/** Only the newly owned staging tree is writable; published trees are never edited. */
export function enhanceStaging(dist, strategy) {
  const pin = strategy?.pin
  if (!pin) throw new TypeError('Unsupported Native Profile brand')
  const target = path.join(dist,pin.file)
  const enhanced = enhanceSource(readFileSync(target,'utf8'),strategy)
  const resources = templateResources(strategy)
  const captured = captureTemplateArtifactContext(strategy.artifactContextDeclaration, {resources,upstreamPackageRoot:path.resolve(dist,'..')})
  chmodSync(target,0o644)
  writeFileSync(target,enhanced)
  stageTemplateGraph(dist,resources)
  const modifiedMember = captured.outputDirectory+'/'+pin.file
  const transformedMembers = captured.edges.some(edge => edge.upstreamMember === modifiedMember)
    ? {[modifiedMember]:createHash('sha256').update(enhanced).digest('hex')} : {}
  verifyTemplateArtifactEmission(path.resolve(dist),captured,{transformedMembers})
  return {id:strategy.ownerId+'-profile',version:1,configurationQuery:'_ordessa/session/configuration',instanceDirectoryRequired:true,
    ...(strategy.managedAccountScope ? {managedAccountScope:true} : {}), upstreamSourceDigest:'sha256:'+pin.digest}
}
const COMMON_RESOURCES = Object.freeze({"ordessa-canonical-json.mjs": fileURLToPath(new URL("../../packages/infrastructure/src/ordessa_infrastructure/encoding/canonical_json.mjs", import.meta.url)),"ordessa-configuration-query.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/digest.mjs", import.meta.url)),"ordessa-configuration-operation.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/operation.mjs", import.meta.url)),"ordessa-native-mechanism.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/bridge.mjs", import.meta.url)),"ordessa-native-evidence-reader.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/reader.mjs", import.meta.url)),"ordessa-restoration.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/restoration.mjs", import.meta.url)),"ordessa-endpoint.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/endpoint.mjs", import.meta.url)),"ordessa-private-scope.mjs": fileURLToPath(new URL("../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/private_scope.mjs", import.meta.url))})

export function templateResources(strategy) { return Object.freeze({...COMMON_RESOURCES,...strategy.resources}) }
