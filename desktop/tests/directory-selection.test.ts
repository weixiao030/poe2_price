import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../src/renderer/stores/app'
import type { AppSettings, GameClient } from '../src/shared/types'

test('a pending directory selection blocks a second selection without clearing its busy state', async () => {
  setActivePinia(createPinia())
  const store = useAppStore()
  const selected = { path: 'D:\\Games\\First', isChina: false } as GameClient
  let completeInspection!: (client: GameClient) => void
  const inspection = new Promise<GameClient>((resolve) => {
    completeInspection = resolve
  })
  const inspected: string[] = []
  const originalWindow = globalThis.window
  Object.assign(globalThis, {
    window: {
      desktop: {
        inspectGame: async (_version: string, directory: string) => {
          inspected.push(directory)
          return directory === selected.path ? inspection : { ...selected, path: directory }
        },
        saveSettings: async (patch: Partial<AppSettings>) => ({ ...store.settings, ...patch }),
        getLeagues: async () => []
      }
    }
  })
  let first: Promise<void> | undefined
  try {
    first = store.selectDirectory(selected.path)
    assert.equal(store.querying, true)
    await assert.rejects(store.selectDirectory('D:\\Games\\Second'), /正在查询游戏目录/)
    assert.equal(store.querying, true)
    assert.deepEqual(inspected, [selected.path])
    completeInspection(selected)
    await first
    assert.equal(store.client?.path, selected.path)
    assert.equal(store.settings.directories.poe2, selected.path)
    assert.equal(store.querying, false)
  } finally {
    completeInspection(selected)
    await first
    Object.assign(globalThis, { window: originalWindow })
    store.dispose()
  }
})

test('directory selection cannot start during a patch operation', async () => {
  setActivePinia(createPinia())
  const store = useAppStore()
  store.state.active = { runId: 'active' } as NonNullable<typeof store.state.active>
  await assert.rejects(store.selectDirectory('D:\\Games\\Other'), /已有任务正在执行/)
  assert.equal(store.querying, false)
})
