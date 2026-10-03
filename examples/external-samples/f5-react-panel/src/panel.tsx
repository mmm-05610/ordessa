/**
 * F5 fixture sample: a React panel with selection bindings and one edit
 * session (R7/M14, T008-13/20). No Agent/Profile/Chat/Harness: proves the
 * F5 mechanisms work for a standalone UI plugin.
 */
import {
  stateStoreFactory,
  type OwnedState,
} from '../../../../packages/desktop-platform/ui-components/src/state/stateStore'
import { createSelector } from '../../../../packages/desktop-platform/ui-components/src/state/selectors'
import { useStoreSelection } from '../../../../packages/desktop-platform/ui-components/react/state'

export interface PanelState {
  title: string
  note: string
  tick: number
}

export class PanelOwner {
  readonly store: OwnedState<PanelState> = stateStoreFactory.createOwned<PanelState>({
    title: 'F5 panel',
    note: '',
    tick: 0,
  })

  setNote(note: string): void {
    this.store.update(s => ({ ...s, note }))
  }

  bump(): void {
    this.store.update(s => ({ ...s, tick: s.tick + 1 }))
  }
}

export function TitleView({ owner }: { owner: PanelOwner }) {
  const title = useStoreSelection(owner.store, createSelector((s: PanelState) => s.title))
  return <h1 data-testid="title">{title}</h1>
}

export function NoteView({ owner }: { owner: PanelOwner }) {
  const note = useStoreSelection(owner.store, createSelector((s: PanelState) => s.note))
  return <p data-testid="note">{note}</p>
}

export function TickView({ owner }: { owner: PanelOwner }) {
  const tick = useStoreSelection(owner.store, createSelector((s: PanelState) => s.tick))
  return <output data-testid="tick">{tick}</output>
}
