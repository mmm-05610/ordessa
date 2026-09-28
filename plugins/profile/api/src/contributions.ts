/**
 * In-memory reference implementation of the Profile contribution registry
 * (contracts.md §2).  Proves the registration semantics: duplicates refused,
 * scope release unloads, scopes are isolated.  Real UIs consume this through
 * DI, not by re-implementing the rules.
 */
import { ResourceScope } from '@ordessa/extension-api'
import { DisposableDelegate, type IDisposable } from '@lumino/disposable'
import type {
  ProfileContributions,
  ProfileContributionsForScope,
  ProfileEditorContribution,
  ProfileSettingsContribution,
} from './contract'

export class DuplicateContributionError extends Error {
  readonly id: string
  constructor(kind: string, id: string) {
    super(`duplicate profile ${kind} id: ${id}`)
    this.id = id
  }
}

interface ScopeRecord {
  editors: Map<string, ProfileEditorContribution>
  settings: Map<string, ProfileSettingsContribution>
}

export class InMemoryProfileContributions implements ProfileContributions {
  private readonly scopes = new WeakMap<ResourceScope, ScopeRecord>()

  private record(scope: ResourceScope): ScopeRecord {
    let record = this.scopes.get(scope)
    if (!record) {
      record = { editors: new Map(), settings: new Map() }
      this.scopes.set(scope, record)
    }
    return record
  }

  forScope(scope: ResourceScope): ProfileContributionsForScope {
    const self = this
    return {
      addEditor(contribution): IDisposable {
        const record = self.record(scope)
        if (record.editors.has(contribution.facetId))
          throw new DuplicateContributionError('editor', contribution.facetId)
        record.editors.set(contribution.facetId, contribution)
        return new DisposableDelegate(() => {
          const current = self.scopes.get(scope)
          if (current && current.editors.get(contribution.facetId) === contribution)
            current.editors.delete(contribution.facetId)
        })
      },
      addSettingsSection(contribution): IDisposable {
        const record = self.record(scope)
        if (record.settings.has(contribution.id))
          throw new DuplicateContributionError('settings section', contribution.id)
        record.settings.set(contribution.id, contribution)
        return new DisposableDelegate(() => {
          const current = self.scopes.get(scope)
          if (current && current.settings.get(contribution.id) === contribution)
            current.settings.delete(contribution.id)
        })
      },
    }
  }

  /** Read-side for hosts/tests: editors of one scope, ordered. */
  editorsOf(scope: ResourceScope): readonly ProfileEditorContribution[] {
    return [...this.record(scope).editors.values()]
      .sort((a, b) => a.order - b.order || a.facetId.localeCompare(b.facetId))
  }

  /** Read-side for hosts/tests: settings sections of one scope, ordered. */
  settingsOf(scope: ResourceScope): readonly ProfileSettingsContribution[] {
    return [...this.record(scope).settings.values()]
      .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
  }
}
