import path from 'node:path'
import { createHarness, request } from './auto-update-harness.mjs'

const root = path.resolve(process.argv[2])
const fresh = createHarness(root)
fresh.schedule()
const beforeFirstUpdate = { confirmed: !!fresh.state.confirmed, scheduled: !!fresh.deadline() }
await fresh.runOperation(request)
const firstDeadline = fresh.deadline()
fresh.schedule()

const restartSeed = createHarness(root)
await restartSeed.runOperation(request)
restartSeed.jump(2 * 60 * 60_000)
const restarted = restartSeed.restart()
restarted.schedule()
await restarted.advance(2_000)

const game = createHarness(root)
await game.runOperation(request)
game.exit = 2
await game.advance(60 * 60_000)
const callsAfterSkip = game.calls
await game.advance(60_000)
const callsAfterOneMinute = game.calls
await game.advance(60_000)

const failed = createHarness(root)
await failed.runOperation(request)
failed.exit = 1
await failed.advance(60 * 60_000)
const retryDelays = [Date.parse(failed.deadline()) - failed.now]
await failed.advance(retryDelays[0])
retryDelays.push(Date.parse(failed.deadline()) - failed.now)
await failed.advance(retryDelays[1])
retryDelays.push(Date.parse(failed.deadline()) - failed.now)

const busy = createHarness(root)
await busy.runOperation(request)
busy.maintenance = true
await busy.advance(60 * 60_000)
const busyRetryMs = Date.parse(busy.deadline()) - busy.now

const restore = createHarness(root)
await restore.runOperation(request)
const beforeRestore = restore.deadline()
await restore.runOperation({ ...request, operation: 'restore' })

const disabled = createHarness(root)
await disabled.runOperation(request)
const queued = disabled.timer
const disabledSettings = disabled.state.settings
disabledSettings.autoUpdate = false
disabled.store.set('settings', disabledSettings)
disabled.schedule()
const callsBeforeDisabledCallback = disabled.calls
await queued.callback()

console.log(
  JSON.stringify(
    {
      beforeFirstUpdate,
      firstSuccessfulUpdateSchedulesHourly: Date.parse(firstDeadline) - fresh.now,
      unrelatedScheduleKeepsDeadline: fresh.deadline() === firstDeadline,
      overdueRestartRunsWithin2s: restarted.calls,
      automaticPreflightQueries: restarted.queries,
      gameRunning: {
        retryMs: Date.parse(game.deadline()) - game.now,
        callsAfterSkip,
        callsAfterOneMinute,
        callsAfterTwoMinutes: game.calls
      },
      failureRetryDelays: retryDelays,
      busyRetryMs,
      restoreKeepsDeadline: restore.deadline() === beforeRestore,
      disabled: {
        deadline: disabled.deadline(),
        queuedCallbackRuns: disabled.calls - callsBeforeDisabledCallback
      }
    },
    null,
    2
  )
)
