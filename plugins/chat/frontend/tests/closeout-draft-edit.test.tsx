import { describe, expect, it } from 'vitest'
import { DraftStore } from '../src/state/draft'

describe('Chat draft F5 edit-session integration', () => {
  it('preserves a same-text edit made after an accepted-send capture', async () => {
    const store = new DraftStore()
    const lease = store.claimEditor('draft', 'editor-a')
    store.setText('draft', 'same text', 'editor-a')
    const capture = store.captureForSend('draft', 'submission-a')

    store.setText('draft', 'intermediate', 'editor-a')
    store.setText('draft', 'same text', 'editor-a')
    await capture.settle('accepted')

    expect(store.read('draft').text).toBe('same text')
    expect(store.read('draft').revision).toBeGreaterThan(capture.composition.revision)
    lease.release()
  })

  it('settles the captured draft after its editor lease closes, without consuming newer text', async () => {
    const store = new DraftStore()
    const lease = store.claimEditor('draft', 'editor-a')
    store.setText('draft', 'sent text', 'editor-a')
    const capture = store.captureForSend('draft', 'submission-b')
    lease.release()

    await capture.settle('accepted')

    expect(store.read('draft').text).toBe('')
    expect(store.read('draft').revision).toBe(capture.composition.revision + 1)
  })

  it('does not consume a replacement pane that happens to reuse the captured revision', async () => {
    const store = new DraftStore()
    store.setText('draft', 'sent text')
    const capture = store.captureForSend('draft', 'submission-replaced')
    store.disposePane('draft')
    store.setText('draft', 'new pane text') // numeric revision can match the old pane

    await capture.settle('accepted')

    expect(store.read('draft').text).toBe('new pane text')
  })

  it('keeps the edit session dirty on refusal or an unknown submission result', async () => {
    for (const outcome of ['refused', 'unknown'] as const) {
      const store = new DraftStore()
      store.setText('draft', `keep-${outcome}`)
      const capture = store.captureForSend('draft', `submission-${outcome}`)

      await capture.settle(outcome)

      expect(store.read('draft').text).toBe(`keep-${outcome}`)
      expect(store.read('draft').revision).toBe(capture.composition.revision)
    }
  })
})
