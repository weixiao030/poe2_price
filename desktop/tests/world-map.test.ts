import { test } from 'node:test'
import assert from 'node:assert/strict'
import { assertMapClient, mapDirectory, mapRoute, overlayPatch } from '../src/main/world-map-policy'
import { settingsPatch } from '../src/main/policy'
import type { GameClient } from '../src/shared/types'
import { overlayDefaults } from '../src/shared/world-map'
import { shouldResumeMap, MAP_CONSENT_VERSION } from '../src/main/world-map-policy'
import { planningPatch, loadPlanning, plannedRequest } from '../src/main/world-map-policy'
import { rankAtlasNodes, safeAtlasSegment, safeAtlasEdge } from '../src/shared/atlas-geometry'
import type { AtlasNode } from '../src/shared/world-map'

test('map remembers last switch only after current risk authorization', () => {
  const preferences = { directory: 'D:\\game', consentVersion: MAP_CONSENT_VERSION }
  assert.equal(shouldResumeMap(preferences), false)
  assert.equal(shouldResumeMap({ ...preferences, enabled: true }), true)
  assert.equal(shouldResumeMap({ ...preferences, enabled: false }), false)
  assert.equal(shouldResumeMap({ ...preferences, enabled: true, consentVersion: 0 }), false)
})
test('planner state survives serialization and rejects forged fields or coordinates', () => {
  const state = loadPlanning({
    query: 'Steppe',
    mode: 'manual',
    start: { x: 1, y: 2 },
    target: { x: 3, y: 4 },
    selected: null
  })
  assert.deepEqual(loadPlanning(JSON.parse(JSON.stringify(state))), state)
  assert.deepEqual(plannedRequest(state), {
    mode: 'manual',
    start: { x: 1, y: 2 },
    target: { x: 3, y: 4 }
  })
  assert.equal(plannedRequest({ ...state, start: null }), null)
  for (const input of [
    { query: 'x'.repeat(81) },
    { mode: 'other' },
    { enabled: true },
    { start: { x: Infinity, y: 2 } }
  ])
    assert.throws(() => planningPatch(input))
})
test('search retains every match, orders by distance and number, and reports signed deltas', () => {
  const nodes = Array.from(
    { length: 151 },
    (_, i) => ({ number: i + 1, grid: { x: i, y: 0 } }) as AtlasNode
  )
  const ranked = rankAtlasNodes(nodes, { x: 149, y: 0 })
  assert.equal(ranked.length, 151)
  assert.equal(ranked[0].number, 150)
  assert.equal(ranked[1].number, 149)
  assert.equal(ranked[1].delta, 'X-1 · Y+0')
  assert.equal(rankAtlasNodes(nodes, null)[0].distance, null)
})
test('overlay rejects torn-frame long lines and large grid spans', () => {
  assert.equal(safeAtlasSegment({ x: 100, y: 100 }, { x: 900, y: 100 }, 1920, 1080), false)
  assert.equal(safeAtlasSegment({ x: 100, y: 100 }, { x: 200, y: 100 }, 1920, 1080), true)
  assert.equal(safeAtlasSegment({ x: NaN, y: 1 }, { x: 1, y: 1 }, 1920, 1080), false)
  assert.equal(safeAtlasEdge({ x: 0, y: 0 }, { x: 17, y: 0 }), false)
  assert.deepEqual(
    overlayPatch({ pathWidth: 6, pathColor: '#12abcd', allowBackground: true, opacity: 10 }),
    { pathWidth: 6, pathColor: '#12abcd', allowBackground: true, opacity: 10 }
  )
  for (const input of [
    { pathWidth: 0 },
    { pathWidth: 7 },
    { pathColor: 'url(x)' },
    { allowBackground: 1 }
  ])
    assert.throws(() => overlayPatch(input))
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
