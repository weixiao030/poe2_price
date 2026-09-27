import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { argsFor, defaults, settingsPatch, validateRequest } from '../src/main/policy'
import { currentAutoUpdateRequest, restoreConfirmedUpdate } from '../src/main/auto-update'
import {
  tabletStatusForRequest,
  wholeTabletStatusForRequest
} from '../src/shared/operation-outcome'
// @ts-expect-error Shared JavaScript clock/worker harness.
import { createHarness, request } from '../scripts/auto-update-harness.mjs'

test('old profiles enable both tablet options, and explicit false survives validation and worker arguments', () => {
  const old = restoreConfirmedUpdate({ request, installKind: 'Intl-Bundles2' })!
  assert.equal(old.request.tabletPrices, true)
  assert.equal(old.request.tabletAffixPrices, true)
  for (const tabletPrices of [true, false])
    for (const tabletAffixPrices of [true, false]) {
      const patch = settingsPatch({ tabletPrices, tabletAffixPrices })
      const validated = validateRequest({ ...request, ...patch })
      assert.equal(argsFor(validated).TabletPrices, tabletPrices)
      assert.equal(argsFor(validated).TabletAffixPrices, tabletAffixPrices)
      assert.equal('TabletPrices' in argsFor({ ...validated, gameVersion: 'poe1' }), false)
    }
  assert.throws(() => settingsPatch({ tabletPrices: 'false' }))
  assert.throws(() => validateRequest({ ...request, tabletAffixPrices: 0 }))
  assert.equal(
    tabletStatusForRequest({ ...request, tabletAffixPrices: false }, 'disabled'),
    undefined
  )
  assert.equal(
    wholeTabletStatusForRequest({ ...request, tabletPrices: false }, 'disabled'),
    undefined
  )
})

test('next scheduled update and restart read saved preferences without another manual update', async () => {
  let harness = createHarness(fileURLToPath(new URL('../', import.meta.url)))
  await harness.runOperation(request)
  harness.store.set('settings', {
    ...harness.state.settings,
    patchScope: 'currency',
    tabletPrices: false,
    tabletAffixPrices: true,
    islandRumourHints: false
  })
  const originalDeadline = harness.deadline()
  harness.schedule()
  assert.equal(harness.deadline(), originalDeadline)
  harness = harness.restart()
  harness.schedule()
  await harness.advance(3_600_000)
  const sent = harness.workerRequests.at(-1)
  assert.equal(sent.automatic, true)
  assert.equal(sent.request.patchScope, 'currency')
  assert.equal(sent.arguments.TabletPrices, false)
  assert.equal(sent.arguments.TabletAffixPrices, true)
  assert.equal(sent.arguments.IslandRumourHints, false)
  assert.equal(sent.request.gameDirectory, request.gameDirectory)
})

test('an unconfirmed client pauses automatic writes until selected back or manually confirmed', async () => {
  const harness = createHarness(fileURLToPath(new URL('../', import.meta.url)))
  await harness.runOperation(request)
  harness.store.set('settings', {
    ...harness.state.settings,
    directories: { poe2: 'D:\\AnotherClient' }
  })
  harness.schedule()
  await harness.advance(3_600_000)
  assert.equal(harness.calls, 1)
  assert.equal(harness.deadline(), null)
  assert.match(harness.autoUpdateStatus(), /客户端已切换/)
})

test('saved CN season and language are used; legacy league choices remain until changed', () => {
  const confirmed = { request: validateRequest(request), installKind: 'CN-WeGame-Bundles2' }
  const settings = { ...defaults, directories: { poe1: '', poe2: request.gameDirectory } }
  assert.equal(currentAutoUpdateRequest(confirmed, settings)!.league, request.league)
  const updated = currentAutoUpdateRequest(confirmed, {
    ...settings,
    leagueSelections: {
      'poe2-china': {
        mode: 'fixed',
        option: {
          Value: 'old',
          Label: '旧赛季',
          ScoutLeague: 'old-scout',
          PoeNinjaLeague: 'Old Ninja',
          PoeCurrencySeason: '0.4',
          IsCurrent: false
        }
      }
    }
  })!
  assert.equal(updated.league, 'old-scout')
  assert.equal(updated.poeCurrencySeason, '0.4')
  assert.equal(updated.leagueIsCurrent, false)
  assert.equal(
    currentAutoUpdateRequest(confirmed, {
      ...settings,
      leagueSelections: {
        'poe2-china': { mode: 'auto' }
      }
    })!.leagueMode,
    'auto'
  )
})
