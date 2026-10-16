import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { enhanceSource as compile, enhanceStaging as stage, templateResources } from "../../../../tooling/generation/harness_native_profile.mjs"
const root = fileURLToPath(new URL("../src/ordessa_harness_codex/acp/profile", import.meta.url))
const artifact = JSON.parse(readFileSync(new URL("../src/ordessa_harness_codex/acp/launch_codex.json",import.meta.url),"utf8"))
const strategy = Object.freeze({
  artifactContextDeclaration: fileURLToPath(new URL("./template_artifact_context.json", import.meta.url)),
  ownerId: "codex", pin: Object.freeze({"file": "index.js", "digest": artifact.nativeExtension.source}),
  getExpression: "getAgent()",
  startAnchor: "function startAcpServer() {",
  promptExpression: "getAgent().prompt(ctx.params, ctx.signal)",
  providerMethods: Object.freeze({"set": "setProvider", "disable": "disableProvider"}),
  imported: "import { captureCodexThreadRoute } from './ordessa-native-routing.mjs';\nimport { writeCodexModelCatalog } from './ordessa-codex-model-catalog.mjs';\nimport { assertNativeCodexSpecifier, assertNativeProcess, assertResumedThread, captureCodexHistory, managedAccountDirectory, orchestrateCodexReplacement, rebindCodexConnection, resolveNativeCodexBinary, spawnNativeCodex, stopNativeProcess } from './ordessa-codex-process.mjs';\n",
  managedAccountScope: true,
  patch(source, once) {
    source = once(source, '  const codexConnection = startCodexConnection(codexPath);\n  const maxStderrTailChars',
      '  let codexConnection = startCodexConnection(codexPath);\n  const maxStderrTailChars')
    // ACP stdin close must release the whole owned native group, not one pid.
    source = once(source,
      '  process.stdin.on("close", () => {\n    codexConnection.process.stdin.end();\n    setTimeout(() => {\n      if (!codexConnection.process.killed) {\n        logger.log("Codex still running 2s after stdin closed; terminating process");\n        codexConnection.process.kill();\n      }\n    }, 2e3);\n  });',
      '  process.stdin.on("close", () => {\n    codexConnection.process.stdin.end();\n    setTimeout(() => {\n      void stopNativeCodexConnection(codexConnection).catch(() => {});\n    }, 2e3);\n  });')
    source = once(source,
      '    return new CodexAcpServer(connection, codexClient, defaultAuthRequest, () => codexConnection.process.exitCode, () => stderr);',
      `    const instance = new CodexAcpServer(connection, codexClient, defaultAuthRequest, () => codexConnection.process.exitCode, () => stderr);
    instance.ordessaPrepareCodexCatalog = async ({model, modelCapabilities}) => {
      if (instance.sessions.size !== 0 || process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR)
        throw new Error('Model catalogue preparation requires a private empty native owner');
      const env = {...process.env, CODEX_HOME: process.env.ORDESSA_NATIVE_INSTANCE_DIR};
      const catalog = writeCodexModelCatalog(env.CODEX_HOME, model, modelCapabilities);
      const previous = codexConnection;
      await stopNativeProcess(previous.process);
      instance.codexAcpClient.ordessaDisconnected = true;
      try {
        codexConnection = startCodexConnection(codexPath, env, catalog);
        await assertNativeCodexChild(codexConnection);
        rebindCodexConnection(instance, {connection: codexConnection.connection,
          AppServerClass: CodexAppServerClient, ClientClass: CodexAcpClient, CommandsClass: CodexCommands,
          config: config2, model, acpConnection: connection,
          runWithProcessCheck: operation => instance.runWithProcessCheck(operation),
          onAuthStateRefresh: () => instance.refreshSessionsAuthState(null)});
        await instance.codexAcpClient.initialize({clientInfo: instance.clientInfo});
      } catch (failure) {
        instance.codexAcpClient.ordessaDisconnected = true;
        if (codexConnection !== previous) {
          try {await stopNativeProcess(codexConnection.process)} catch {failure.nativeCleanupFailed = true}
        }
        throw failure;
      }
    };
    instance.ordessaReplaceCodexProcess = async ({sessionId, model, provider, modelCapabilities}) => {
      const current = instance.codexAcpClient;
      // Read this owner's live thread before any native effect. A sibling thread,
      // an unpersisted thread or a damaged rollout refuses with zero effects.
      const rollout = await captureCodexHistory({client: current, sessionId,
        home: current.getHomePath(), previouslyOwnedPath: current.ordessaOwnedRolloutPath});
      const env = {...process.env, CODEX_HOME: process.env.ORDESSA_NATIVE_INSTANCE_DIR};
      delete env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR;
      const managed = provider.authentication === 'managed-account';
      if (managed) {
        env.CODEX_HOME = managedAccountDirectory(provider.accountDirectory, env.ORDESSA_NATIVE_INSTANCE_DIR);
        env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = env.CODEX_HOME;
      }
      const catalog = modelCapabilities === undefined ? undefined
        : writeCodexModelCatalog(env.CODEX_HOME, model, modelCapabilities);
      await instance.closeSession({sessionId});
      const previous = codexConnection;
      // Publish the new child immediately so ACP shutdown always owns it, and
      // never spawn before the old native owner's exit is authoritatively
      // confirmed. Any failure leaves the old binding invalid.
      await orchestrateCodexReplacement({instance, sessionId,
        capture: async () => rollout,
        stop: () => stopNativeProcess(previous.process),
        start: () => {
          codexConnection = startCodexConnection(codexPath, env, catalog);
          stderr = '';
          codexConnection.process.stderr.addListener('data', data => {
            stderr = (stderr + data.toString()).slice(-maxStderrTailChars);
          });
          return codexConnection;
        },
        initialize: async () => {
          await assertNativeCodexChild(codexConnection);
          rebindCodexConnection(instance, {connection: codexConnection.connection,
            AppServerClass: CodexAppServerClient, ClientClass: CodexAcpClient, CommandsClass: CodexCommands,
            config: config2, model, rolloutPath: rollout, acpConnection: connection,
            runWithProcessCheck: operation => instance.runWithProcessCheck(operation),
            onAuthStateRefresh: () => instance.refreshSessionsAuthState(null)});
          const fresh = instance.codexAcpClient;
          await fresh.initialize({clientInfo: instance.clientInfo});
          if (managed) {
            const account = await fresh.codexClient.accountRead({refreshToken: true});
            if (account.account?.type !== 'chatgpt') throw new Error('Managed account login required');
          }
        }});
      process.env.CODEX_HOME = env.CODEX_HOME;
      if (managed) process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR = env.CODEX_HOME;
      else delete process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR;
      return {sessionId, rolloutPath: rollout};
    };
    return instance;`)
    source = once(source, '      threadId: request.sessionId\n    });\n    onSubscribed?.();\n    const codexModels',
      '      threadId: request.sessionId,\n      ...(this.ordessaResumeRolloutPath ? {path: this.ordessaResumeRolloutPath} : {})\n    });\n    assertResumedThread(response, request.sessionId, this.ordessaResumeRolloutPath);\n    onSubscribed?.();\n    const codexModels')
    source = once(source,
      '.onRequest(methods.agent.authenticate, (ctx) => getAgent().authenticate(ctx.params, ctx.requestId))',
      '.onRequest(methods.agent.authenticate, (ctx) => ordessaProfile(getAgent()).withExternalProvider(() => getAgent().authenticate(ctx.params, ctx.requestId)))')
    // Only the explicit managed route may read native account state. ACP
    // session clients cannot replace/cancel/logout that shared account.
    for (const name of ['accountLogin(params)', 'accountLoginCancel(params)', 'accountLogout()']) {
      source = once(source, `  async ${name} {`,
        `  async ${name} {\n    if (process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR) throw new Error('Managed account changes require the account owner');`)
    }
    // Launch the verified native binary directly from inside the enhanced
    // artifact. The Node launcher spawns that binary with stdio: "inherit" and
    // forwards only SIGINT/SIGTERM/SIGHUP, so a launcher pid is never proof of
    // native exit; resolution and platform selection stay Harness-internal.
    source = once(source, '  const spawnEnv = env ?? process.env;',
      `  const spawnEnv = env ?? process.env;
  const ordessaArgs = spawnEnv.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR ? ['-c', 'cli_auth_credentials_store="keyring"', 'app-server'] : ['app-server'];
  if (modelCatalogPath !== undefined) ordessaArgs.unshift('-c', 'model_catalog_json=' + JSON.stringify(modelCatalogPath));
  if (spawnEnv.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR && process.platform === 'win32') throw new Error('Managed account launch is not supported on this platform');
  const ordessaNativeCodex = resolveNativeCodexBinary();`)
    source = once(source,
      'codex = process.platform === "win32" ? spawn(`"${codexPath}" app-server`, { shell: true, env: spawnEnv }) : spawn(codexPath, ["app-server"], { env: spawnEnv });',
      'codex = spawnNativeCodex({nativeBinary: codexPath ? assertNativeCodexSpecifier(codexPath, ordessaNativeCodex) : ordessaNativeCodex, args: ordessaArgs, env: spawnEnv});')
    source = once(source, 'codex = spawn(process.execPath, [bundledCodexPath, "app-server"], { env: spawnEnv });',
      'codex = spawnNativeCodex({nativeBinary: ordessaNativeCodex, args: ordessaArgs, env: spawnEnv});')
    source = once(source, '  return { connection, process: codex };',
      '  codex.ordessaNativeCodex = ordessaNativeCodex;\n  return { connection, process: codex };')
    // Module scope, not inside startCodexConnection: the ACP shutdown handler and
    // the replacement owner below both close a native child from elsewhere.
    source = once(source, 'function startCodexConnection(codexPath, env) {',
      `// Bound: only the OS exit event plus an empty owned process set proves exit.
function stopNativeCodexConnection(connection) {
  return stopNativeProcess(connection.process, {graceMs: 2e3, terminateMs: 2e3, killMs: 2e3});
}
async function assertNativeCodexChild(connection) {
  const child = connection.process;
  const identity = await child.ordessaNativeIdentity;
  assertNativeProcess(identity.pid, child.ordessaNativeCodex);
  return identity;
}
function startCodexConnection(codexPath, env, modelCatalogPath) {`)
    // Upstream raw RPC tracing can include login tokens and provider headers.
    // The enhanced artifact never installs that trace hook on its child.
    source = once(source, '  attachLogs(codex);', '  // Raw native RPC tracing disabled by Ordessa.')
    for (const [name, method] of [['threadStart', 'thread/start'], ['threadResume', 'thread/resume']]) {
      source = once(source,
        `  async ${name}(params) {\n    return await this.sendRequest({ method: "${method}", params });\n  }`,
        `  async ${name}(params) {\n    this.ordessaThreadRoutes ??= new Map();\n    if (this.ordessaThreadRoutes.size >= 256 && !this.ordessaThreadRoutes.has(params.threadId)) throw new Error('Native route capacity exhausted');\n    let managedAccountVerified = false;\n    if (process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR && [undefined, null, 'openai'].includes(params.modelProvider)) {\n      const account = await this.accountRead({refreshToken: true});\n      if (account.account?.type !== 'chatgpt') throw new Error('Managed account login required');\n      managedAccountVerified = true;\n    }\n    const submittedRoute = captureCodexThreadRoute(params, { modelProvider: params.modelProvider });\n    const response = await this.sendRequest({ method: "${method}", params });\n    const route = submittedRoute ?? captureCodexThreadRoute(params, response, {managedAccountVerified});\n    if (route && response.modelProvider === route.provider) this.ordessaThreadRoutes.set(response.thread.id, route);\n    else this.ordessaThreadRoutes.delete(response.thread.id);\n    return response;\n  }`)
    }
  
    return source
  },
  resources: Object.freeze({
    "ordessa-profile.mjs": path.join(root, "entry.mjs"),
    "ordessa-native-profile.mjs": path.join(root, "bridge.mjs"),
    "ordessa-native-configuration-query.mjs": path.join(root, "configuration-query.mjs"),
    "ordessa-native-routing.mjs": path.join(root, "routing.mjs"),
    "ordessa-native-strategy.mjs": path.join(root, "strategy.mjs"),
    "ordessa-codex-process.mjs": path.join(root, "codex-process.mjs"),
    "ordessa-codex-model-catalog.mjs": path.join(root, "codex-model-catalog.mjs"),
    "codex-generic-prompt.md": path.join(root, "codex-generic-prompt.md"),
    "codex-generic-prompt.LICENSE": path.join(root, "codex-generic-prompt.LICENSE"),
    "codex-generic-prompt.NOTICE": path.join(root, "codex-generic-prompt.NOTICE"),
  })
})
export function enhanceSource(source) { return compile(source,strategy) }
export function enhanceStaging(dist) { return stage(dist,strategy) }

export function enhancementTemplateResources() { return templateResources(strategy) }

export function templateArtifactContextDeclaration() { return strategy.artifactContextDeclaration }
