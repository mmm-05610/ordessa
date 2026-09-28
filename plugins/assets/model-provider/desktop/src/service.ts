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
    get probeCalls() { return probeCalls },
    list: (includeArchived = false) => wire.list(includeArchived).then((page) => page.items),
    testConnection: countProbe((baseUrl, credentialId) => wire.probeConnection(baseUrl, credentialId)),
    fetchModels: countProbe((baseUrl, credentialId) => wire.probeModels(baseUrl, credentialId)),
    async save(body, edit) {
      const answer = edit === undefined
        ? await wire.create(body)
        : await wire.update({ ...body, providerModelId: edit.id, expectedVersion: edit.version })
      return answer.providerModel
    },
  }
}

export type { ProviderConfigView, ProbeAnswer }
