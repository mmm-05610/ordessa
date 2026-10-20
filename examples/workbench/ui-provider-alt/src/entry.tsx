// Controlled provider B: the same key, a different providerId. Selecting it is a
// product-configuration change only — the consumer bundle is byte-identical (U02, V05).
import type * as API from '@ordessa/extension-api'
import { UiComponentsToken, registration, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { WidgetKey, type WidgetProps } from '@extensions/example.ui-contracts/contract.js'

const Widget = ({ title }: WidgetProps) => <p data-testid="widget">provider-b {title}</p>

export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.ui-provider-alt', autoStart: true, requires: [UiComponentsToken],
    activate(_host, owned, ui: UiComponents) {
      ui.forScope(owned).register({ key: WidgetKey, providerId: 'example.provider-b', component: Widget })
    } })
}
