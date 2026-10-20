// Controlled consumer: binds the test-domain key and renders whatever the product
// selected through the platform Outlet. It never imports a provider (UI-01/V05).
import type * as API from '@ordessa/extension-api'
import { UiComponentsToken, type UiBinding, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { WidgetKey, type WidgetProps } from '@extensions/example.ui-contracts/contract.js'
import { ComponentOutlet, useUiBinding } from '@ordessa/ui-components/react'

function ConsumerView({ binding }: { binding: UiBinding<WidgetProps> }) {
  const availability = useUiBinding(binding)
  return <section data-testid="ui-consumer">
    <span data-testid="availability">{availability.status === 'ready' ? `ready:${availability.providerId}`
      : availability.status === 'missing' ? `missing:${availability.reason}` : availability.status}</span>
    <ComponentOutlet binding={binding} value={{ title: 'from-consumer', onAct: () => undefined }}
      missing={<span data-testid="absent">absent</span>} />
  </section>
}

export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.ui-consumer', autoStart: true, requires: [UiComponentsToken],
    activate(host, owned, ui: UiComponents) {
      const binding = ui.forScope(owned).bind(WidgetKey, { required: true })
      owned.add(host.root.mount({ id: 'example.ui-consumer', component: () => <ConsumerView binding={binding} /> }))
    } })
}
