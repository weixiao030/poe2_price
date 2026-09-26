import { test } from 'node:test'
import assert from 'node:assert/strict'
import { OperationOutput } from '../src/main/operation-output'
import { operationWarning, tabletStatusForRequest, wholeTabletStatusForRequest } from '../src/shared/operation-outcome'
import type { OperationResult, PatchRequest } from '../src/shared/types'

const request = { operation: 'update', gameVersion: 'poe2', patchScope: 'all' } as PatchRequest
const result = { exitCode: 0, cancelled: false, ...request } as OperationResult

test('final tablet marker survives chunk splits, UTF-8 text and log truncation', () => {
  const marker = '__POE_TABLET_LAYER__unavailable\r\n'
  for (let split = 0; split <= marker.length; split++) {
    const output = new OperationOutput()
    output.write('中文构建日志\r\n' + marker.slice(0, split))
    output.write(marker.slice(split) + '后续日志'.repeat(100_000))
    output.end()
    assert.equal(output.tabletAffixes, 'unavailable')
  }
  const output = new OperationOutput()
  output.write('quoted __POE_TABLET_LAYER__applied\n__POE_TABLET_LAYER__invalid\n')
  assert.equal(output.tabletAffixes, undefined)
  output.write('__POE_TABLET_LAYER__applied')
  output.end()
  assert.equal(output.tabletAffixes, 'applied')
})

test('only requested POE2 tablet layers are interpreted', () => {
  for (const patchScope of ['all', 'currency'] as const) {
    assert.equal(tabletStatusForRequest({ ...request, patchScope }, undefined), 'unknown')
    assert.equal(tabletStatusForRequest({ ...request, patchScope }, 'disabled'), 'unknown')
    assert.equal(tabletStatusForRequest({ ...request, patchScope }, 'applied'), 'applied')
  }
  for (const change of [
    { patchScope: 'uniques' },
    { patchScope: 'none' },
    { gameVersion: 'poe1' },
    { operation: 'restore' },
    { operation: 'localize' }
  ])
    assert.equal(
      tabletStatusForRequest({ ...request, ...change } as PatchRequest, 'unavailable'),
      undefined
    )
})

test('partial results remain visible after saving history, without overriding failure or cancellation', () => {
  const partial = { ...result, tabletAffixes: 'unavailable' as const }
  assert.match(operationWarning(JSON.parse(JSON.stringify(partial)))!, /碑牌词缀未生效/)
  assert.match(operationWarning({ ...result, tabletAffixes: 'unknown' })!, /未能确认/)
  assert.equal(operationWarning({ ...result, tabletAffixes: 'applied' }), undefined)
  assert.equal(operationWarning(result), undefined) // Existing history has no layer field.
  for (const change of [{ cancelled: true }, { skipped: true }, { exitCode: 1 }])
    assert.equal(operationWarning({ ...partial, ...change }), undefined)
})

test('whole tablet result is independent of affix success and works for uniques-only', () => {
  for (let split = 0; split < 40; split++) {
    const marker = '__POE_WHOLE_TABLETS__unavailable\r\n'
    const output = new OperationOutput()
    output.write('__POE_TABLET_LAYER__applied\n' + marker.slice(0, split))
    output.write(marker.slice(split) + '日志'.repeat(10000))
    output.end()
    assert.equal(output.wholeTablets, 'unavailable')
    assert.equal(output.tabletAffixes, 'applied')
    assert.match(operationWarning({ ...result, ...output })!, /整件\/暗金碑牌价格未完整生效/)
  }
  for (const patchScope of ['all', 'currency', 'uniques'] as const)
    assert.equal(wholeTabletStatusForRequest({ ...request, patchScope }, 'unavailable'), 'unavailable')
  assert.equal(wholeTabletStatusForRequest(request, 'disabled'), undefined)
  assert.equal(wholeTabletStatusForRequest(request, undefined), undefined)
  assert.equal(wholeTabletStatusForRequest({ ...request, patchScope: 'none' }, 'unavailable'), undefined)
  assert.equal(wholeTabletStatusForRequest({ ...request, gameVersion: 'poe1' }, 'unavailable'), undefined)
  assert.equal(operationWarning({ ...result, wholeTablets: 'applied' }), undefined)
  assert.equal(operationWarning({ ...result, wholeTablets: 'unavailable', cancelled: true }), undefined)
})
