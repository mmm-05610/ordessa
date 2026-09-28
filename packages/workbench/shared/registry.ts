import { Contributions, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
/** Internal helper, not another host service or dependency scheduler. */
export function registry<T extends { id: string; order?: number }>(lifetime: ResourceScope) {
  const values = lifetime.add(new Contributions<T>())
  return {
    getSnapshot: values.getSnapshot, subscribe: values.subscribe,
    add(scope: ResourceScope, item: T): IDisposable {
      if (scope.isDisposed || lifetime.isDisposed) throw Error('Registration scope is closed')
      if (!item.id.trim()) throw Error('Contribution id is required')
      return scope.add(values.add(Object.freeze({ ...item })))
    },
  }
}
export function ordered<T extends { id: string; order?: number }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id))
}
