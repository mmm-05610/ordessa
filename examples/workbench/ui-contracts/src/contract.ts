// The controlled test domain of the C7/C8 gates: one generic widget interface.
// It lives in its OWN carrier, not in the platform carrier, which is what makes
// it a real test of开放性 (C8 V05: a new component kind needs no platform change).
import { defineUiComponent } from '@extensions/ordessa.contracts/contract.js'

export interface WidgetProps { readonly title: string; readonly onAct: () => void }

/** Constructed exactly once for this host build; the key identity rule (UI-02) is what the gates check. */
export const WidgetKey = defineUiComponent<WidgetProps>('example.widget', 1)
