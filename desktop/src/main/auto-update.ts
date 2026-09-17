import path from 'node:path'
import { text, validateRequest } from './policy'
import type { OperationResult, PatchRequest } from '../shared/types'

export interface ConfirmedUpdate {
  request: PatchRequest
  installKind: string
  successAt?: string
}
export interface AutoUpdateSchedule {
  nextAttemptAt: string
  failures: number
  reason: 'interval' | 'startup' | 'busy' | 'game' | 'retry' | 'cancelled'
}
export const UPDATE_INTERVAL = 60 * 60_000
export const BUSY_RETRY = 60_000
export const GAME_RETRY = 2 * 60_000

// A damaged or legacy confirmation must never turn a scheduled update into a
// restore/localization operation or discard the user's auto-update preference.
export function restoreConfirmedUpdate(value: unknown): ConfirmedUpdate | null {
  try {
    const candidate = value as ConfirmedUpdate
    const request = validateRequest(candidate.request)
    const installKind = text(candidate.installKind, 160)
    if (request.operation !== 'update' || !installKind) return null
    return {
      request,
      installKind,
      ...(typeof candidate.successAt === 'string' &&
      Number.isFinite(Date.parse(candidate.successAt))
        ? { successAt: candidate.successAt }
        : {})
    }
  } catch {
    return null
  }
}

export function restoreAutoUpdateSchedule(
  saved: AutoUpdateSchedule | null | undefined,
  confirmed: ConfirmedUpdate | null,
  history: OperationResult[],
  now: number
): AutoUpdateSchedule | null {
  if (!confirmed) return null
  const due = Date.parse(saved?.nextAttemptAt ?? '')
  if (Number.isFinite(due)) {
    return {
      // A backwards wall-clock change must not postpone updates indefinitely.
      nextAttemptAt: new Date(Math.min(due, now + UPDATE_INTERVAL)).toISOString(),
      failures: Math.min(3, Math.max(0, Math.trunc(Number(saved?.failures) || 0))),
      reason: ['interval', 'startup', 'busy', 'game', 'retry', 'cancelled'].includes(
        saved?.reason ?? ''
      )
        ? saved!.reason
        : 'startup'
    }
  }
  const last = (Array.isArray(history) ? history : []).find(
    (result) =>
      result &&
      result.operation === 'update' &&
      result.exitCode === 0 &&
      !result.cancelled &&
      !result.skipped &&
      typeof result.gameDirectory === 'string' &&
      result.gameVersion === confirmed.request.gameVersion &&
      path.win32.resolve(result.gameDirectory).toLowerCase() ===
        path.win32.resolve(confirmed.request.gameDirectory).toLowerCase()
  )
  const success = Date.parse(confirmed.successAt ?? '')
  const completed = Number.isFinite(success)
    ? success
    : last
      ? Date.parse(last.startedAt) +
        (Number.isFinite(last.durationMs) ? Math.max(0, last.durationMs) : 0)
      : NaN
  return {
    nextAttemptAt: new Date(
      Number.isFinite(completed)
        ? Math.min(completed + UPDATE_INTERVAL, now + UPDATE_INTERVAL)
        : now
    ).toISOString(),
    failures: 0,
    reason: Number.isFinite(completed) ? 'interval' : 'startup'
  }
}

export function scheduleAfterUpdate(
  previous: AutoUpdateSchedule | null | undefined,
  result: OperationResult,
  now: number
): AutoUpdateSchedule | null | undefined {
  if (result.operation !== 'update') return previous
  if (result.exitCode === 0 && !result.cancelled)
    return {
      nextAttemptAt: new Date(now + UPDATE_INTERVAL).toISOString(),
      failures: 0,
      reason: 'interval'
    }
  // A failed manual update may target a different client; keep the confirmed plan.
  if (!result.automatic) return previous
  const failures = Math.min(3, (previous?.failures || 0) + 1)
  const reason = result.cancelled ? 'cancelled' : result.skipped ? 'game' : 'retry'
  const delay = result.cancelled
    ? 5 * 60_000
    : result.skipped
      ? GAME_RETRY
      : [60_000, 5 * 60_000, 15 * 60_000][failures - 1]
  return {
    nextAttemptAt: new Date(now + delay).toISOString(),
    failures: reason === 'retry' ? failures : previous?.failures || 0,
    reason
  }
}
