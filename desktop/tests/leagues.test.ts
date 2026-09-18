import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../src/renderer/stores/app'
import { defaults, settingsPatch, validateRequest } from '../src/main/policy'
import { restoreConfirmedUpdate } from '../src/main/auto-update'
import type { DesktopApi, LeagueOption, PatchRequest } from '../src/shared/types'

const old: LeagueOption = {
  Value: 'Old',
  Label: 'Old',
  ScoutLeague: 'old-id',
  PoeNinjaLeague: 'Old',
  PoeCurrencySeason: '',
  IsCurrent: false
}
const current: LeagueOption = {
  Value: 'New',
  Label: 'New',
  ScoutLeague: 'new-id',
  PoeNinjaLeague: 'New',
  PoeCurrencySeason: '',
  IsCurrent: true
}
function setup(overrides: Partial<DesktopApi> = {}) {
  setActivePinia(createPinia())
  const store = useAppStore()
  const requests: PatchRequest[] = []
  const api = {
    getLeagues: async () => [current, old],
    saveSettings: async (patch: unknown) => ({
      ...store.settings,
      ...settingsPatch(structuredClone(patch))
    }),
    runOperation: async (request: PatchRequest) => {
      requests.push(request)
      return { exitCode: 0 }
    },
    ...overrides
  }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { desktop: api } })
  store.state.settings = structuredClone(defaults)
  store.client = {
    gameVersion: 'poe2',
    path: 'D:\\Games\\POE2',
    displayName: 'POE2',
    installKind: 'Steam',
    isChina: false,
    language: 'Chinese'
  }
  return { store, requests }
}

test('new profiles follow latest and keep auto mode in the confirmed hourly request', async () => {
  const { store, requests } = setup()
  await store.refreshLeagues()
  assert.equal(store.selectedLeague, '__auto__')
  assert.equal(store.league?.Value, 'New')
  await store.run('update')
  assert.equal(requests[0].leagueMode, 'auto')
  const confirmed = restoreConfirmedUpdate({ request: requests[0], installKind: 'Steam' })!
  assert.equal(confirmed.request.leagueMode, 'auto')
  assert.equal(confirmed.request.league, 'new-id')
})

test('a pinned league survives missing directory entries and refresh failure', async () => {
  let online = true
  const { store, requests } = setup({
    getLeagues: async () => {
      if (!online) throw new Error('offline')
      return [current]
    }
  })
  store.leagues = [old]
  await store.selectLeague('Old')
  await store.refreshLeagues()
  assert.equal(store.league?.ScoutLeague, 'old-id')
  online = false
  await store.refreshLeagues()
  assert.equal(store.selectedLeague, 'Old')
  assert.match(store.leagueNotice, /保留/)
  await store.run('update')
  assert.equal(requests[0].leagueMode, 'fixed')
  assert.equal(requests[0].league, 'old-id')
  assert.equal(store.settings.leagueSelections?.['poe2-international']?.mode, 'fixed')
})

test('reopening a client restores its own pinned selection while other scopes default to auto', async () => {
  const { store } = setup({
    inspectGame: async (version, directory) => ({
      gameVersion: version,
      path: directory,
      displayName: 'POE2',
      installKind: 'Fixture',
      isChina: directory.includes('CN'),
      language: 'Chinese'
    })
  })
  store.leagues = [old]
  await store.selectLeague('Old')
  await store.selectDirectory('D:\\Games\\POE2')
  assert.equal(store.selectedLeague, 'Old')
  await store.selectDirectory('D:\\Games\\CN')
  assert.equal(store.selectedLeague, '__auto__')
  await store.selectDirectory('D:\\Games\\POE2')
  assert.equal(store.selectedLeague, 'Old')
})

test('a stale refresh cannot replace the catalogue after switching client scope', async () => {
  let finish!: (value: LeagueOption[]) => void
  const { store } = setup({
    getLeagues: async () =>
      new Promise((resolve) => {
        finish = resolve
      }),
    inspectGame: async () => ({
      gameVersion: 'poe2',
      path: 'D:\\Games\\CN',
      displayName: 'CN',
      installKind: 'CN',
      isChina: true,
      language: 'Chinese'
    })
  })
  const pending = store.refreshLeagues()
  const oldFinish = finish
  await store.selectDirectory('D:\\Games\\CN')
  oldFinish([old])
  await pending
  assert.equal(store.leagues.length, 0)
  finish([
    { ...current, Value: '0.5.5', ScoutLeague: '', PoeNinjaLeague: '', PoeCurrencySeason: '0.5.5' }
  ])
  await Promise.resolve()
})

test('auto mode can retry after first-load discovery failure without requiring a fabricated league', async () => {
  const { store, requests } = setup({
    getLeagues: async () => {
      throw new Error('offline')
    }
  })
  await store.refreshLeagues()
  assert.equal(store.league, undefined)
  assert.equal(store.leagueOptions[0].value, '__auto__')
  await store.run('update')
  assert.equal(requests[0].leagueMode, 'auto')
  assert.equal(requests[0].league, '')
})

test('settings validate saved season identities and legacy requests keep their fixed selection', () => {
  assert.throws(() => settingsPatch({ leagueSelections: { 'poe3-china': { mode: 'auto' } } }))
  assert.throws(() => settingsPatch({ leagueSelections: { 'poe2-china': { mode: 'fixed' } } }))
  assert.throws(() =>
    settingsPatch({
      leagueSelections: {
        'poe2-international': { mode: 'fixed', option: { ...old, ScoutLeague: 'bad\nargument' } }
      }
    })
  )
  const { store } = setup()
  const legacy = validateRequest({
    operation: 'update',
    gameVersion: 'poe2',
    gameDirectory: store.client!.path,
    patchScope: 'all',
    languageMode: 'auto',
    islandRumourHints: true,
    league: 'old-id',
    poeNinjaLeague: 'Old',
    poeCurrencySeason: '',
    leagueIsCurrent: false
  })
  assert.equal(legacy.leagueMode, 'fixed')
})
