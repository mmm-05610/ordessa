// Type-level counterexamples for the C8 `@ordessa/ui` public surface (UIB002,
// plan "最小公开基础件" upper bound + F03/F05/F06). Never bundled, never
// runtime-loaded: a relaxed type silently fails this file because each of the
// expect-error directives below must actually fire. Check command (this
// file is deliberately outside the desktop tsconfig `include`, which only
// covers */src):
//   npx tsc --noEmit --strict --jsx react-jsx --target ES2022 --module ESNext \
//     --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck tests/ui.typecheck.ts
import { createElement } from 'react'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Field,
  IconButton,
  Input,
  Notice,
  Panel,
  ScrollArea,
  Separator,
  Toolbar,
} from '../src/index'
import type { FieldControlState, IconButtonProps } from '../src/index'

// --- positives: the shapes the contract promises are usable as written -------
const named: IconButtonProps = { 'aria-label': 'Close dialog', busy: true, size: 'sm' }
void named
void createElement(IconButton, { 'aria-label': 'Close dialog' })
void createElement(Card.Root, { variant: 'subtle', padding: 'lg', 'aria-label': 'card' })
void createElement(Panel.Root, null,
  createElement(Panel.Body, null, createElement(ScrollArea, { direction: 'both' })),
)
void createElement(Button, { type: 'submit', busy: false, onClick: () => undefined })
void createElement(Notice, { tone: 'warning', live: true, title: 'heads up' })
void createElement(Separator, { orientation: 'vertical', semantic: true })
// Field.Control hands its a11y bundle to the consumer's real control — the
// documented render-prop exception, spreadable onto a native input.
void createElement(Field.Control, {
  children: (state: FieldControlState) => createElement(Input, state),
})

// --- negatives ---------------------------------------------------------------
// @ts-expect-error An IconButton without an accessible name does not compile — type-level requirement, not a runtime warning.
void createElement(IconButton, {})

// @ts-expect-error Card takes no registry props: components load via children, never via componentId (F03/C8 ruling 3).
void createElement(Card.Root, { componentId: 'git.diff' })

// @ts-expect-error ...nor a providerId.
void createElement(Card.Root, { providerId: 'provider-a' })

// @ts-expect-error ...and no business mode booleans.
void createElement(Card.Root, { isChat: true, approvalMode: false })

// @ts-expect-error Panel is likewise children-only; no registry hook on the body.
void createElement(Panel.Body, { providerId: 'x' })

// @ts-expect-error Badge tone is one of five generic tones; tones never encode an execution result.
void createElement(Badge, { tone: 'approved' })

// @ts-expect-error Notice's live region is an explicit opt-in boolean, not a free-form announcement mode.
void createElement(Notice, { live: 'assertive' })

// @ts-expect-error ScrollArea directions are the closed native-overflow set.
void createElement(ScrollArea, { direction: 'diagonal' })

// @ts-expect-error Toolbar exposes role="group"; consumers cannot restamp it as a roving-tabindex toolbar.
void createElement(Toolbar, { role: 'toolbar' })

// @ts-expect-error Field.Control children must be the render function carrying the id bundle — plain nodes are not accepted.
void createElement(Field.Control, { children: 'just a string' })

// @ts-expect-error Field takes no validation schema; it wires ids and presentation states only (F04).
void createElement(Field.Root, { schema: { name: 'z.string()' } })

// @ts-expect-error An explicit undefined accessible name is still missing — required means required.
void createElement(IconButton, { 'aria-label': undefined })

// @ts-expect-error Checkbox is native and fixed to type="checkbox"; its type cannot be restamped.
void createElement(Checkbox, { type: 'radio' })
