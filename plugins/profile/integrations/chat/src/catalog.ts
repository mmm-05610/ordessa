import type { ProfileCatalogGroup, ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'

/** Event-driven directory; one request at a time and no late updates after unload. */
export class ProfileCatalog {
  groups: readonly ProfileCatalogGroup[] = []
  message = '正在读取预设目录…'
  private revision = 0
  private disposed = false
  get isDisposed() { return this.disposed }
  private pending?: Promise<void>
  private readonly listeners = new Set<() => void>()
  constructor(private readonly profiles: Pick<ProfileServiceClient, 'profileCatalog'>) {}
  getSnapshot = () => this.revision
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private publish() { this.revision += 1; for (const listener of this.listeners) listener() }
  refresh = (): Promise<void> => {
    if (this.disposed) return Promise.resolve()
    if (this.pending) return this.pending
    this.message = '正在读取预设目录…'
    this.publish()
    this.pending = Promise.resolve().then(async () => {
      try {
        const groups = await this.profiles.profileCatalog('local')
        if (this.disposed) return
        this.groups = groups
        this.message = groups.length ? '' : '暂无可用预设；创建后可刷新目录。'
      } catch (error) {
        if (this.disposed) return
        this.groups = []
        this.message = `读取预设目录失败：${error instanceof Error ? error.message : String(error)}`
      } finally {
        this.pending = undefined
        if (!this.disposed) this.publish()
      }
    })
    return this.pending
  }
  dispose() { this.disposed = true; this.listeners.clear() }
}
