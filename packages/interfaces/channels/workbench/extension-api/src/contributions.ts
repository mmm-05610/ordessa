import { DisposableDelegate, type IDisposable } from '@lumino/disposable';
import { Signal } from '@lumino/signaling';

/** Shared contribution primitive; plugin lifecycle is owned by Lumino. */
export class Contributions<T extends { id: string }> implements IDisposable {
  private values = new Map<string, T>();
  private snapshot: readonly T[] = [];
  private changed = new Signal<this, void>(this);
  isDisposed = false;
  getSnapshot = (): readonly T[] => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.changed.connect(listener);
    return () => { this.changed.disconnect(listener); };
  };
  add(value: T): IDisposable {
    if (this.isDisposed) throw new Error('Contribution point is disposed');
    if (this.values.has(value.id)) throw new Error(`Duplicate contribution: ${value.id}`);
    this.values.set(value.id, value);
    this.publish();
    return new DisposableDelegate(() => {
      if (this.values.get(value.id) === value) {
        this.values.delete(value.id);
        this.publish();
      }
    });
  }
  dispose(): void {
    if (this.isDisposed) return;
    this.isDisposed = true;
    this.values.clear();
    this.publish();
    Signal.clearData(this);
  }
  private publish(): void {
    this.snapshot = [...this.values.values()].sort((a, b) => a.id.localeCompare(b.id));
    this.changed.emit();
  }
}
