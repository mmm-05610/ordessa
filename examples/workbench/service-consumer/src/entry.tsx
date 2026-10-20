import type * as API from '@ordessa/extension-api'
import { GreetingToken, type Greeting } from '@extensions/example.contracts/contract.js'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.consumer', autoStart: true, requires: [GreetingToken, WorkbenchToken], activate(host, owned, greeting: Greeting, workbench: Workbench) {
    workbench.forScope(owned).addView({ id: 'example.consumer.page', title: 'Service', presentation: 'region', region: 'main', component: () => <p>{greeting.message}</p> })
  } })
}
