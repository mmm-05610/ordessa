// Controlled provider A for the C7/C8 gates: registers one implementation of the
// test-domain key and renders nothing until the product selects it (U01/U02).
import type * as API from '@ordessa/extension-api'
import { UiComponentsToken, registration, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { WidgetKey, type WidgetProps } from '@extensions/example.ui-contracts/contract.js'

const Widget = ({ title, onAct }: WidgetProps) =>
  <p data-testid="widget">provider-a {title} <button type="button" onClick={onAct}>act</button></p>

export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.ui-provider', autoStart: true, requires: [UiComponentsToken],
    activate(_host, owned, ui: UiComponents) {
      ui.forScope(owned).registerBatch([registration(WidgetKey, 'example.provider-a', Widget)])
    } })
}
