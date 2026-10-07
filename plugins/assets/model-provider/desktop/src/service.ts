// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/service.ts, verbatim)
import { wireThrough, type ModelProviderService, type ModelProviderWire,
         type ProviderConfigView, type ProbeAnswer } from '../../contracts/index'

export function createModelProviderService(invoke: Parameters<typeof wireThrough>[0]): ModelProviderService {
  const wire: ModelProviderWire = wireThrough(invoke)
  let probeCalls = 0
  const countProbe = <A extends unknown[]>(run: (...args: A) => Promise<ProbeAnswer>) =>
    (...args: A) => { probeCalls += 1; return run(...args) }
  return {
    wire,
    importApiKey: (requestId, harnessId, apiKey) => wire.importApiKey(requestId, harnessId, apiKey),
    queryApiKeyImport: (requestId, harnessId) => wire.queryApiKeyImport(requestId, harnessId),
    get probeCalls() { return probeCalls },
    list: (includeArchived = false) => wire.list(includeArchived).then((page) => page.items),
    testConnection: countProbe((baseUrl, credentialId) => wire.probeConnection(baseUrl, credentialId)),
    fetchModels: countProbe((baseUrl, credentialId) => wire.probeModels(baseUrl, credentialId)),
    async save(body, edit) {
      const requestId = body.requestId ?? `save_${globalThis.crypto.randomUUID()}`
      const { harness: _harness, provider: _provider, providerModelId: _id, expectedVersion: _version, ...mutable } = body
      const answer = edit === undefined
        ? await wire.create({ ...body, requestId })
        : await wire.update({ ...mutable, requestId, providerModelId: edit.id, expectedVersion: edit.version })
      return answer.providerModel
    },
  }
}

export type { ProviderConfigView, ProbeAnswer }
