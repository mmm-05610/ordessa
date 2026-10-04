import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { createFileUiAdapter } from '@ordessa/native-bridge/ui-storage'
import { fileBackedUiStore } from '@ordessa/ui-components/ui-storage'
import { UiSchemaUnknownError } from '../../contracts/foundation/src/open-environment/f5/errors'

const roots: string[] = []

async function temporaryRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'ordessa-public-versioned-ui-'))
  roots.push(root)
  return root
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true })))
})

describe('public versioned UI storage with the native file adapter', () => {
  it('shares first-create and revision CAS across independent public stores', async () => {
    const root = await temporaryRoot()
    const namespace = {
      pluginNamespace: 'fixture.layout',
      workspace: 'workspace-a',
      windowOrSharedPurpose: 'shared-layout',
      schemaVersion: 1,
    }
    const otherNamespace = { ...namespace, pluginNamespace: 'fixture.other-layout' }
    const first = fileBackedUiStore(createFileUiAdapter(root))
    const second = fileBackedUiStore(createFileUiAdapter(root))

    expect((await first.readVersioned(namespace, 'layout')))
      .toEqual({ value: undefined, revision: null })
    const firstCreates = await Promise.all([
      first.writeVersioned(namespace, 'layout', { panes: { left: { width: 320 } } }, null),
      second.writeVersioned(namespace, 'layout', { panes: { left: { width: 640 } } }, null),
    ])
    expect(firstCreates.sort()).toEqual(['conflict', 'written'])

    const createdByFirst = await first.readVersioned<{ panes: { left: { width: number } } }>(namespace, 'layout')
    const createdBySecond = await second.readVersioned<{ panes: { left: { width: number } } }>(namespace, 'layout')
    expect(createdByFirst).toEqual(createdBySecond)
    expect(typeof createdByFirst.revision).toBe('string')
    expect(createdByFirst.revision).not.toBe('')
    const capturedRevision = createdByFirst.revision
    expect(capturedRevision).not.toBeNull()
    if (capturedRevision === null) throw new Error('successful first creation must expose its revision')

    const competingWrites = await Promise.all([
      first.writeVersioned(namespace, 'layout', { panes: { left: { width: 400 } } }, capturedRevision),
      second.writeVersioned(namespace, 'layout', { panes: { left: { width: 800 } } }, capturedRevision),
    ])
    expect(competingWrites.sort()).toEqual(['conflict', 'written'])
    expect(await first.writeVersioned(namespace, 'layout', { panes: { left: { width: 1 } } }, capturedRevision))
      .toBe('conflict')

    const winnerSnapshot = await second.readVersioned<{ panes: { left: { width: number } } }>(namespace, 'layout')
    winnerSnapshot.value!.panes.left.width = 1
    const persistedWinner = await first.readVersioned<{ panes: { left: { width: number } } }>(namespace, 'layout')
    expect(persistedWinner.value?.panes.left.width).toBeGreaterThan(1)
    expect(persistedWinner.revision).not.toBe(capturedRevision)

    expect(await first.readVersioned(otherNamespace, 'layout'))
      .toEqual({ value: undefined, revision: null })

    const schemaLimited = fileBackedUiStore(createFileUiAdapter(root), {
      supportedSchemaVersions: [1],
    })
    await expect(schemaLimited.readVersioned({ ...namespace, schemaVersion: 99 }, 'layout'))
      .rejects.toThrow(UiSchemaUnknownError)
    await expect(schemaLimited.writeVersioned({ ...namespace, schemaVersion: 99 }, 'layout', { width: 1 }, null))
      .rejects.toThrow(UiSchemaUnknownError)

    // The old public write face keeps its pre-increment undefined = unconditional meaning.
    expect(await first.write(namespace, 'layout', { width: 777 }, { ifRevision: undefined }))
      .toBe('written')
    expect((await second.readVersioned<{ width: number }>(namespace, 'layout')).value)
      .toEqual({ width: 777 })
  })
})
