import type * as API from '@ordessa/extension-api'
import { GreetingToken } from '@extensions/example.contracts/contract.js'
export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.provider-alt', provides: GreetingToken, activate() { return { message: 'Replacement provider connected' } } })
}
