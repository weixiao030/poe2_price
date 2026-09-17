import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { restoreAutoUpdateSchedule, restoreConfirmedUpdate } from '../src/main/auto-update'

test('auto-update catches up after restart and retries without tight polling', () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const probe = fileURLToPath(new URL('../scripts/check-auto-update-contract.mjs', import.meta.url))
  const observed = JSON.parse(execFileSync(process.execPath, [probe, root], { encoding: 'utf8' }))
  assert.deepEqual(observed.beforeFirstUpdate, { confirmed: false, scheduled: false })
  assert.equal(observed.firstSuccessfulUpdateSchedulesHourly, 3_600_000)
  assert.equal(observed.unrelatedScheduleKeepsDeadline, true)
  assert.equal(observed.overdueRestartRunsWithin2s, 1)
  assert.equal(observed.automaticPreflightQueries, 0)
  assert.equal(observed.gameRunning.retryMs, 120_000)
  assert.equal(observed.gameRunning.callsAfterSkip, observed.gameRunning.callsAfterOneMinute)
  assert.equal(observed.gameRunning.callsAfterTwoMinutes, observed.gameRunning.callsAfterSkip + 1)
  assert.deepEqual(observed.failureRetryDelays, [60_000, 300_000, 900_000])
  assert.equal(observed.busyRetryMs, 60_000)
  assert.equal(observed.restoreKeepsDeadline, true)
  assert.deepEqual(observed.disabled, { deadline: null, queuedCallbackRuns: 0 })
})

test('disk failure pauses automatic writes instead of repeating an overdue operation', async () => {
  // The harness executes production functions; only the clock, store and engine are inert.
  // @ts-expect-error JavaScript harness intentionally has no declaration file.
  const { createHarness, request } = await import('../scripts/auto-update-harness.mjs')
  const harness = createHarness(fileURLToPath(new URL('../', import.meta.url)))
  await harness.runOperation(request)
  harness.failWrites = true
  await harness.advance(3_600_000)
  assert.equal(harness.calls, 2)
  assert.equal(harness.deadline(), null)
  await harness.advance(24 * 3_600_000)
  assert.equal(harness.calls, 2)
  assert.equal(harness.state.settings.autoUpdate, true)
})

test('turning off while an automatic task runs invalidates future and stale callbacks', async () => {
  // @ts-expect-error JavaScript harness intentionally has no declaration file.
  const { createHarness, request } = await import('../scripts/auto-update-harness.mjs')
  const harness = createHarness(fileURLToPath(new URL('../', import.meta.url)))
  await harness.runOperation(request)
  const stale = harness.timer
  let finish!: () => void
  harness.engineWait = new Promise<void>((resolve) => {
    finish = resolve
  })
  const running = harness.runOperation(request, true)
  harness.store.set('settings', { ...harness.state.settings, autoUpdate: false })
  harness.schedule()
  finish()
  await running
  await stale.callback()
  await harness.advance(2 * 3_600_000)
  assert.equal(harness.calls, 2)
  assert.equal(harness.deadline(), null)
})

test('invalid confirmation cannot schedule restore or crash startup', async () => {
  // @ts-expect-error JavaScript harness intentionally has no declaration file.
  const { request } = await import('../scripts/auto-update-harness.mjs')
  for (const value of [
    null,
    {},
    { request: { ...request, operation: 'restore' }, installKind: 'Fixture' }
  ])
    assert.equal(restoreConfirmedUpdate(value), null)
  const confirmed = restoreConfirmedUpdate({
    request,
    installKind: 'Fixture',
    successAt: 'invalid'
  })!
  assert.ok(confirmed)
  const now = Date.UTC(2026, 8, 17)
  assert.equal(
    restoreAutoUpdateSchedule(null, confirmed, [null] as never, now)?.nextAttemptAt,
    new Date(now).toISOString()
  )
  const future = {
    nextAttemptAt: new Date(now + 86400_000).toISOString(),
    failures: Infinity,
    reason: 'retry' as const
  }
  assert.deepEqual(restoreAutoUpdateSchedule(future, confirmed, [], now), {
    nextAttemptAt: new Date(now + 3_600_000).toISOString(),
    failures: 3,
    reason: 'retry'
  })
})
