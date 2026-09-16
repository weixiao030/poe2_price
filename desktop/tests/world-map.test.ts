import { test } from 'node:test'
import assert from 'node:assert/strict'
import { assertMapClient, mapDirectory, mapRoute, overlayPatch } from '../src/main/world-map-policy'
import { settingsPatch } from '../src/main/policy'
import type { GameClient } from '../src/shared/types'
import { overlayDefaults } from '../src/shared/world-map'
import { shouldResumeMap, MAP_CONSENT_VERSION } from '../src/main/world-map-policy'

test('map remembers last switch only after current risk authorization', () => {
  const preferences = { directory: 'D:\\game', consentVersion: MAP_CONSENT_VERSION }
  assert.equal(shouldResumeMap(preferences), false)
  assert.equal(shouldResumeMap({ ...preferences, enabled: true }), true)
  assert.equal(shouldResumeMap({ ...preferences, enabled: false }), false)
  assert.equal(shouldResumeMap({ ...preferences, enabled: true, consentVersion: 0 }), false)
})

test('game overlay shows names, numbers and connections by default', () => {
  assert.equal(overlayDefaults.names, true)
  assert.equal(overlayDefaults.numbers, true)
  assert.equal(overlayDefaults.connections, true)
})
test('world map denies CN, POE1 and unknown clients at the main-process boundary', () => {
  const client: GameClient = {
    gameVersion: 'poe2',
    path: 'D:\\game',
    displayName: '',
    installKind: 'Intl-Standalone-GGPK',
    isChina: false,
    language: ''
  }
  assert.doesNotThrow(() => assertMapClient(client))
  assert.doesNotThrow(() => assertMapClient({ ...client, installKind: 'Intl-Bundles2' }))
  for (const patch of [
    { gameVersion: 'poe1' },
    { isChina: true },
    { installKind: 'CN-WeGame-Bundles2' },
    { installKind: 'unknown' }
  ])
    assert.throws(() => assertMapClient({ ...client, ...patch } as GameClient))
})
test('map consent and enable state cannot be forged through generic settings IPC', () => {
  for (const field of ['worldMap', 'consentVersion', 'worldMapEnabled', 'authorized'])
    assert.throws(() => settingsPatch({ [field]: true }))
})
test('world map route and directory inputs are bounded and typed', () => {
  assert.equal(mapDirectory('D:\\中文目录'), 'D:\\中文目录')
  for (const input of ['relative', '\\\\host\\share', '', 'D:\\x\n'])
    assert.throws(() => mapDirectory(input))
  assert.deepEqual(mapRoute({ mode: 'current', target: { x: 1, y: 2 } }), {
    mode: 'current',
    target: { x: 1, y: 2 }
  })
  for (const input of [
    { mode: 'manual', target: { x: 1, y: 2 } },
    { mode: 'x', target: { x: 1, y: 2 } },
    { mode: 'current', target: { x: NaN, y: 0 } },
    { mode: 'current', target: { x: 1.5, y: 0 } },
    { mode: 'current', target: { x: 2e6, y: 0 } }
  ])
    assert.throws(() => mapRoute(input))
})
test('overlay options reject unknown flags, forged opacity and non-boolean switches', () => {
  assert.deepEqual(overlayPatch({ names: true, visible: false, opacity: 50 }), {
    names: true,
    visible: false,
    opacity: 50
  })
  for (const input of [
    { interactive: true },
    { opacity: 0 },
    { opacity: 1000 },
    { opacity: '80' },
    { names: 1 },
    null
  ])
    assert.throws(() => overlayPatch(input))
})
