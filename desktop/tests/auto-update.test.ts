import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

test('hourly preference survives operations; only manual off stops future checks', () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const probe = fileURLToPath(new URL('../scripts/check-auto-update-contract.mjs', import.meta.url))
  const observed = JSON.parse(execFileSync(process.execPath, [probe, root], { encoding: 'utf8' }))
  assert.deepEqual(observed.beforeFirstUpdate, {
    enabled: true,
    confirmed: false,
    scheduled: false
  })
  for (const phase of [
    'enabledAfterSuccess',
    'afterRestore',
    'afterFailedHour',
    'afterSkippedHour'
  ])
    assert.deepEqual(observed[phase], { enabled: true, confirmed: true, scheduled: true }, phase)
  assert.equal(observed.unrelatedSettingsKeepDeadline, true)
  assert.deepEqual(observed.afterManualOff, { enabled: false, confirmed: true, scheduled: false })
  assert.equal(observed.disabledQueuedCallbackRuns, 0)
  assert.equal(
    observed.mapRunningGameHour.calls,
    1,
    'map session must not suppress hourly game detection'
  )
  assert.equal(
    observed.mapRunningGameHour.exitCode,
    2,
    'running game still causes safe skip in engine'
  )
  assert.equal(
    observed.mapWaitingGameHour.calls,
    1,
    'map waiting for game must not suppress patch worker'
  )
  assert.equal(observed.mapWaitingGameHour.exitCode, 0)
  assert.equal(observed.mapWaitingGameHour.mapEnabled, true)
  assert.equal(observed.mapWaitingGameHour.scheduled, true)
})
