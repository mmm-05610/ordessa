// Controlled C8 fixture (V03/V04/V05/V06): the generic foundations composed in a
// real Workbench region, with the C7 Outlet loading a provider component inside a
// Card. It contributes no business meaning — the labels are demo text, the loaded
// component comes from another extension selected by the product configuration.
import type * as API from '@ordessa/extension-api'
import { UiComponentsToken, WorkbenchToken, type UiBinding, type UiComponents, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { WidgetKey, type WidgetProps } from '@extensions/example.ui-contracts/contract.js'
import { ComponentOutlet, useUiBinding } from '@ordessa/ui-components/react'
import {
  Badge, Button, Card, EmptyState, Field, Input, Notice, Panel, ScrollArea, Stack, Toolbar,
} from '@ordessa/ui'

function Probe({ binding }: { binding: UiBinding<WidgetProps> }) {
  const availability = useUiBinding(binding)
  return <Stack spacing="md">
    <span data-testid="availability">{availability.status === 'ready' ? `ready:${availability.providerId}`
      : availability.status === 'missing' ? `missing:${availability.reason}` : availability.status}</span>
    <Card.Root variant="outlined" data-testid="card">
      <Card.Header>
        <Card.Title>Loaded component preview</Card.Title>
        <Card.Actions>
          <Toolbar aria-label="card actions">
            <Button data-testid="ui-button" variant="primary">Refresh</Button>
          </Toolbar>
        </Card.Actions>
      </Card.Header>
      <Card.Body>
        <Panel.Root data-testid="panel">
          <Panel.Header data-testid="panel-header"><Panel.Title>Scroll owner</Panel.Title></Panel.Header>
          <Panel.Body data-testid="panel-body">
            <ScrollArea data-testid="scroll" direction="vertical">
              <div style={{ width: '2400px' }}>a line far wider than any narrow container</div>
            </ScrollArea>
          </Panel.Body>
          <Panel.Footer><Badge tone="info">demo</Badge></Panel.Footer>
        </Panel.Root>
        <Field.Root>
          <Field.Label>Draft</Field.Label>
          <Field.Control>{attributes => <Input {...attributes} data-testid="ui-input" value="kept by the consumer" readOnly onChange={() => undefined} />}</Field.Control>
          <Field.Description>the value is owned by the consumer</Field.Description>
        </Field.Root>
        {/* The C7 mechanism loads the provider's component here; Card knows nothing about it. */}
        <ComponentOutlet binding={binding} value={{ title: 'inside a Card', onAct: () => undefined }}
          missing={<EmptyState title="no component selected" />} />
        <Notice title="heads up">generic feedback, no live region by default</Notice>
      </Card.Body>
    </Card.Root>
    {/* Deliberately outside the foundations classes: the host sheet must keep owning it. */}
    <button data-testid="foreign" type="button">host styled</button>
  </Stack>
}

export default function createPlugin(api: typeof API) {
  return api.scoped({ id: 'example.ui-foundations', autoStart: true, requires: [UiComponentsToken, WorkbenchToken],
    activate(_host, owned, ui: UiComponents, workbench: Workbench) {
      const binding = ui.forScope(owned).bind(WidgetKey, { required: false })
      workbench.forScope(owned).addView({
        id: 'example.ui-foundations.page', title: 'UI probe', presentation: 'region', region: 'main',
        component: () => <Probe binding={binding} />,
      })
    } })
}
