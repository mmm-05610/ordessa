// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (contracts/index.ts, verbatim)
import { Token } from '@ordessa/extension-api'
import type { ModelProviderService } from './service'

export * from './states'
export * from './service'

export const ModelProviderToken = new Token<ModelProviderService>('ordessa.model-provider.v1')
