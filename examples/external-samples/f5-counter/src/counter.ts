/**
 * F5 fixture sample: a plain-TypeScript counter with one owner and two
 * independent consumers (R7/M14, T008-13/20). No React, no Agent/Profile/
 * Chat/Harness: the F5 state mechanism is usable outside every business
 * domain. The tests build this source together with the platform's state
 * store from repo source (controlled fixture wiring, declared in README).
 */
import {
  stateStoreFactory,
  type OwnedState,
} from '../../../../packages/desktop-platform/ui-components/src/state/stateStore'
import {
  createSelector,
  selectionReader,
  type SelectionReader,
} from '../../../../packages/desktop-platform/ui-components/src/state/selectors'

export interface CounterState {
  count: number
  label: string
  history: readonly string[]
}

/** The domain owner: it alone holds the write face. */
export class CounterOwner {
  readonly store: OwnedState<CounterState> = stateStoreFactory.createOwned<CounterState>({
    count: 0,
    label: 'f5-counter',
    history: [],
  }, {
    equals: (a, b) => a.count === b.count && a.label === b.label && a.history === b.history,
  })

  increment(): void {
    this.store.update(s => ({
      ...s,
      count: s.count + 1,
      history: Object.freeze([...s.history, `+1 -> ${s.count + 1}`]),
    }))
  }

  /** Batched rename + increment: consumers see exactly ONE complete snapshot. */
  relabelAndIncrement(label: string): void {
    this.store.updateBatched([
      s => ({ ...s, label }),
      s => ({ ...s, count: s.count + 1 }),
    ])
  }

  reader() {
    return this.store.reader()
  }
}

/** A consumer: read-only count selection. */
export function countConsumer(owner: CounterOwner): SelectionReader<CounterState, number> {
  return selectionReader(owner.reader(), createSelector((s: CounterState) => s.count))
}

/** A second consumer: read-only label selection. */
export function labelConsumer(owner: CounterOwner): SelectionReader<CounterState, string> {
  return selectionReader(owner.reader(), createSelector((s: CounterState) => s.label))
}
