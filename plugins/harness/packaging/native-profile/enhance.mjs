import { createHash } from 'node:crypto'
import { chmodSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PINS = {
  codex: { file: 'index.js', digest: '9634b5457e44d55471d0969bcc5a2a1d4cbb83ba637eaf023d34d2e975fd7db8' },
  'claude-code': { file: 'acp-agent.js', digest: '36a33a984624541ea013c085f5bd1d982294cfe70beb42826752f62bdc538d64' },
}
function once(source, before, after) {
  if (source.split(before).length !== 2) throw new Error('Native Profile patch anchor drift')
  return source.replace(before, after)
}
export function enhanceSource(source, brand) {
  const pin = PINS[brand]
  if (!pin || createHash('sha256').update(source).digest('hex') !== pin.digest)
    throw new Error('Native Profile upstream source digest mismatch')
  const get = brand === 'codex' ? 'getAgent()' : 'agent'
  const setup = `\nconst ordessaBridges = new WeakMap();\nfunction ordessaProfile(instance) {\n  let bridge = ordessaBridges.get(instance);\n  if (!bridge) {\n    bridge = nativeProfileBridge(instance, ${JSON.stringify(brand)}, message => RequestError.invalidParams(undefined, message));\n    ordessaBridges.set(instance, bridge);\n  }\n  return bridge;\n}\n`
  source = once(source, brand === 'codex' ? 'function startAcpServer() {' : 'export function runAcp(logger) {',
    setup + (brand === 'codex' ? 'function startAcpServer() {' : 'export function runAcp(logger) {'))
  source = once(source, `.onRequest(methods.agent.initialize, (ctx) => ${get}.initialize(ctx.params))`,
    `.onRequest(methods.agent.initialize, async (ctx) => { const result = await ${get}.initialize(ctx.params); return { ...result, _meta: { ...result._meta, ordessaConfiguration: { supported: true, version: 1 } } }; })`)
  source = once(source,
    `.onRequest(methods.agent.session.setConfigOption, (ctx) => ${get}.setSessionConfigOption(ctx.params))`,
    `.onRequest(methods.agent.session.setConfigOption, (ctx) => ordessaProfile(${get}).operation.withSession(ctx.params.sessionId, () => ${get}.setSessionConfigOption(ctx.params)))`)
  for (const [method, impl] of [['new', 'newSession'], ['load', 'loadSession'],
    ['resume', 'resumeSession'], ['close', 'closeSession'], ['delete', 'deleteSession']])
    source = once(source, `.onRequest(methods.agent.session.${method}, (ctx) => ${get}.${impl}(ctx.params))`,
      `.onRequest(methods.agent.session.${method}, (ctx) => ordessaProfile(${get}).${['new', 'load', 'resume'].includes(method) ? `withCreation(ctx.params, params => ${get}.${impl}(params)` : `withLifecycle(() => ${get}.${impl}(ctx.params)`}))`)
  const prompt = brand === 'codex' ? `${get}.prompt(ctx.params, ctx.signal)` : 'runPromptWithCancellation(agent, ctx.params, ctx.signal)'
  source = once(source, `.onRequest(methods.agent.session.prompt, (ctx) => ${prompt})`,
    `.onRequest(methods.agent.session.prompt, (ctx) => ordessaProfile(${get}).operation.withSession(ctx.params.sessionId, () => ${prompt}))`)
  for (const method of ['set', 'disable']) {
    const impl = brand === 'codex' ? `${method}Provider` : `unstable_${method}Provider`
    source = once(source, `.onRequest(methods.agent.providers.${method}, (ctx) => ${get}.${impl}(ctx.params))`,
      `.onRequest(methods.agent.providers.${method}, (ctx) => ordessaProfile(${get}).withProvider(() => ${get}.${impl}(ctx.params)))`)
  }
  const registration = `.onRequest('_ordessa/session/configuration', { parse: input => ordessaProfile(${get}).parser.parse(input) }, ctx => ordessaProfile(${get}).read(ctx.params))
    .onRequest('_ordessa/channel/configuration/prepare', { parse: input => ordessaProfile(${get}).creationParser.parse(input) }, ctx => ordessaProfile(${get}).prepareCreation(ctx.params))
    .onRequest('_ordessa/channel/configuration/operation', { parse: input => ordessaProfile(${get}).creationQueryParser.parse(input) }, ctx => ordessaProfile(${get}).queryCreation(ctx.params))
    .onRequest('_ordessa/session/configuration/apply', { parse: input => ordessaProfile(${get}).operation.parseApply(input) }, ctx => ordessaProfile(${get}).apply(ctx.params))
    .onRequest('_ordessa/session/configuration/restore', { parse: input => ordessaProfile(${get}).restoration.parse(input) }, ctx => ordessaProfile(${get}).restoration.apply(ctx.params))
    .onRequest('_ordessa/session/configuration/operation', { parse: input => ordessaProfile(${get}).operation.parseQuery(input) }, ctx => ordessaProfile(${get}).queryOperation(ctx.params))
    `
  source = once(source, '.onRequest(methods.agent.session.setMode,', registration + '.onRequest(methods.agent.session.setMode,')
  if (brand === 'claude-code') {
    source = once(source, '                providerCacheKey,',
      '                providerCacheKey,\n                ordessaProviderRoute: { apiType: resolvedProvider?.apiType ?? null, baseUrl: resolvedProvider?.baseUrl ?? null },')
    source = once(source, 'ANTHROPIC_AUTH_TOKEN: "acp-proxy", // Bypass local Claude login checks',
      'ANTHROPIC_AUTH_TOKEN: claudeProviderAuthToken(config.headers), // Private provider credential, not login placeholder')
  }
  if (brand === 'codex') {
    // Only the explicit managed route may read native account state. ACP
    // session clients cannot replace/cancel/logout that shared account.
    for (const name of ['accountLogin(params)', 'accountLoginCancel(params)', 'accountLogout()']) {
      source = once(source, `  async ${name} {`,
        `  async ${name} {\n    if (process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR) throw new Error('Managed account changes require the account owner');`)
    }
    source = once(source, '  const spawnEnv = env ?? process.env;',
      `  const spawnEnv = env ?? process.env;\n  const ordessaArgs = spawnEnv.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR ? ['-c', 'cli_auth_credentials_store="keyring"', 'app-server'] : ['app-server'];\n  if (spawnEnv.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR && process.platform === 'win32') throw new Error('Managed account launch is not supported on this platform');`)
    source = once(source, 'spawn(codexPath, ["app-server"], { env: spawnEnv })',
      'spawn(codexPath, ordessaArgs, { env: spawnEnv })')
    source = once(source, 'spawn(process.execPath, [bundledCodexPath, "app-server"], { env: spawnEnv })',
      'spawn(process.execPath, [bundledCodexPath, ...ordessaArgs], { env: spawnEnv })')
    // Upstream raw RPC tracing can include login tokens and provider headers.
    // The enhanced artifact never installs that trace hook on its child.
    source = once(source, '  attachLogs(codex);', '  // Raw native RPC tracing disabled by Ordessa.')
    for (const [name, method] of [['threadStart', 'thread/start'], ['threadResume', 'thread/resume']]) {
      source = once(source,
        `  async ${name}(params) {\n    return await this.sendRequest({ method: "${method}", params });\n  }`,
        `  async ${name}(params) {\n    this.ordessaThreadRoutes ??= new Map();\n    if (this.ordessaThreadRoutes.size >= 256 && !this.ordessaThreadRoutes.has(params.threadId)) throw new Error('Native route capacity exhausted');\n    const route = captureCodexThreadRoute(params, { modelProvider: params.modelProvider });\n    const response = await this.sendRequest({ method: "${method}", params });\n    if (route && response.modelProvider === route.provider) this.ordessaThreadRoutes.set(response.thread.id, route);\n    else this.ordessaThreadRoutes.delete(response.thread.id);\n    return response;\n  }`)
    }
  }
  // Preserve a CLI shebang as the first line.
  const imported = "import { nativeProfileBridge } from './ordessa-native-profile.mjs';\n"
    + (brand === 'codex' ? "import { captureCodexThreadRoute } from './ordessa-native-routing.mjs';\n"
      : "import { claudeProviderAuthToken } from './ordessa-claude-auth.mjs';\n")
  source = source.startsWith('#!') ? source.replace('\n', '\n' + imported) : imported + source
  return source
}

/** Called only on the builder's new staging tree, before full tree hashing. */
export function enhanceStaging(dist, brand) {
  const pin = PINS[brand]
  if (!pin) throw new Error('Unsupported Native Profile brand')
  const target = path.join(dist, pin.file)
  const enhanced = enhanceSource(readFileSync(target, 'utf8'), brand)
  const files = {
    ...(brand === 'claude-code' ? {'ordessa-claude-auth.mjs': readFileSync(path.join(HERE, 'claude-auth.mjs'), 'utf8')} : {}),
    'ordessa-profile.mjs': readFileSync(path.join(HERE, 'entry.mjs'), 'utf8').replace('__ORDESSA_NATIVE_BRAND__', brand),
    'ordessa-native-profile.mjs': readFileSync(path.join(HERE, 'bridge.mjs'), 'utf8'),
    'ordessa-native-configuration-query.mjs': readFileSync(path.join(HERE, 'configuration-query.mjs'), 'utf8')
      .replace("'../pi-profile/configuration-query.mjs'", "'./ordessa-configuration-query.mjs'")
      .replace("'./routing.mjs'", "'./ordessa-native-routing.mjs'"),
    'ordessa-native-routing.mjs': readFileSync(path.join(HERE, 'routing.mjs'), 'utf8'),
    'ordessa-configuration-query.mjs': readFileSync(path.join(HERE, '../pi-profile/configuration-query.mjs'), 'utf8'),
    'ordessa-configuration-operation.mjs': readFileSync(path.join(HERE, '../pi-profile/configuration-operation.mjs'), 'utf8'),
    'ordessa-restoration.mjs': readFileSync(path.join(HERE, 'restoration.mjs'), 'utf8'),
  }
  // copyTree preserves read-only source modes. This is the newly created
  // private staging copy; the builder re-seals it before publication.
  chmodSync(target, 0o644)
  writeFileSync(target, enhanced)
  for (const [name, content] of Object.entries(files)) writeFileSync(path.join(dist, name), content)
  return { id: brand + '-profile', version: 1,
    configurationQuery: '_ordessa/session/configuration', instanceDirectoryRequired: true,
    upstreamSourceDigest: 'sha256:' + pin.digest }
}
