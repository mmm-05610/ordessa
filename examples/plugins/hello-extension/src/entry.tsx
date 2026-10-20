import { useState } from 'react'
import type * as API from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
function Hello() {
  const [count, setCount] = useState(0)
  return <section><h1>独立加载的扩展</h1><button data-testid="increment" onClick={() => setCount(c => c + 1)}>Count: {count}</button></section>
}
export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.hello', autoStart: true, requires: [WorkbenchToken], activate(host, owned, workbench: Workbench) {
    workbench.forScope(owned).addView({ id: 'example.hello.page', title: 'Hello', presentation: 'region', region: 'main', component: Hello })
  } })
}
