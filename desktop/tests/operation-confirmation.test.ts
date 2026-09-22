import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../src/renderer/stores/app'
import type { GameClient, PatchRequest } from '../src/shared/types'

test('confirmation preserves its directory and options across later selection changes', async () => {
  setActivePinia(createPinia())
  const store = useAppStore()
  store.client = { path: 'C:\\Fixture\\first', displayName: 'first' } as GameClient
  const confirmed = store.prepareRequest('restore')
  store.client = { path: 'C:\\Fixture\\second', displayName: 'second' } as GameClient
  store.state.settings.patchScope = 'none'
  let received: PatchRequest | undefined
  const originalWindow = globalThis.window
  Object.assign(globalThis, { window: { desktop: { runOperation: async (request: PatchRequest) => {
    received = request
    return { exitCode: 0 }
  } } } })
  try {
    await store.run(confirmed)
    assert.equal(received?.gameDirectory, 'C:\\Fixture\\first')
    assert.equal(received?.patchScope, 'all')
    store.querying = true
    assert.throws(() => store.prepareRequest('restore'), /正在查询游戏目录/)
  } finally {
    Object.assign(globalThis, { window: originalWindow })
    store.dispose()
  }
})
