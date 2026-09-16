import path from 'node:path'
import { boolean, choice, text } from './policy'
import type { GameClient } from '../shared/types'
import type {
  GridPoint,
  RouteRequest,
  OverlayOptions,
  MapPreferences,
  MapPlanningState
} from '../shared/world-map'
import { planningDefaults } from '../shared/world-map'

export const MAP_CONSENT_VERSION = 1
export function shouldResumeMap(preferences: MapPreferences) {
  return preferences.enabled === true && preferences.consentVersion === MAP_CONSENT_VERSION
}
export function assertMapClient(client: GameClient) {
  if (
    client.gameVersion !== 'poe2' ||
    client.isChina ||
    !['Intl-Standalone-GGPK', 'Intl-Bundles2'].includes(client.installKind)
  )
    throw new Error('世界地图规划仅限 POE2 国际服，禁止在国服或其他服使用')
}
export function mapDirectory(input: unknown) {
  const directory = text(input)
  if (!path.win32.isAbsolute(directory) || directory.startsWith('\\\\') || directory.length < 4)
    throw new Error('请选择本机 POE2 国际服目录')
  return directory
}
function grid(input: unknown): GridPoint {
  if (!input || typeof input !== 'object') throw new Error('节点坐标无效')
  const { x, y } = input as GridPoint
  if (![x, y].every((n) => Number.isInteger(n) && Math.abs(n) <= 1_000_000))
    throw new Error('节点坐标无效')
  return { x, y }
}
export function mapRoute(input: unknown): RouteRequest {
  if (!input || typeof input !== 'object') throw new Error('路线参数无效')
  const value = input as RouteRequest
  const mode = choice(value.mode, ['accessible', 'current', 'manual'])
  return {
    mode,
    target: grid(value.target),
    ...(mode === 'manual' ? { start: grid(value.start) } : {})
  }
}
export function overlayPatch(input: unknown): Partial<OverlayOptions> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('覆盖层设置无效')
  const patch: Partial<OverlayOptions> = {}
  for (const [key, value] of Object.entries(input)) {
    if (key === 'opacity') {
      if (typeof value !== 'number' || !Number.isInteger(value) || value < 10 || value > 100)
        throw new Error('覆盖层透明度必须在 10 到 100 之间')
      patch.opacity = value
    } else if (key === 'pathWidth') {
      if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 6)
        throw new Error('路线线宽必须在 1 到 6 之间')
      patch.pathWidth = value
    } else if (key === 'pathColor') {
      if (typeof value !== 'string' || !/^#[0-9a-f]{6}$/i.test(value))
        throw new Error('路线颜色无效')
      patch.pathColor = value
    } else if (
      ['visible', 'numbers', 'names', 'hidden', 'connections', 'allowBackground'].includes(key)
    )
      patch[key as 'visible' | 'numbers' | 'names' | 'hidden' | 'connections' | 'allowBackground'] =
        boolean(value)
    else throw new Error('未知覆盖层设置')
  }
  return patch
}
export function planningPatch(input: unknown): Partial<MapPlanningState> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('路线状态无效')
  const patch: Partial<MapPlanningState> = {}
  for (const [key, value] of Object.entries(input)) {
    if (key === 'query') patch.query = text(value, 80)
    else if (key === 'mode') patch.mode = choice(value, ['accessible', 'current', 'manual'])
    else if (key === 'start' || key === 'target' || key === 'selected')
      patch[key] = value === null ? null : grid(value)
    else throw new Error('未知路线状态')
  }
  return patch
}
export function loadPlanning(input: unknown): MapPlanningState {
  try {
    return { ...planningDefaults, ...planningPatch(input ?? {}) }
  } catch {
    return { ...planningDefaults }
  }
}
export function plannedRequest(state: MapPlanningState): RouteRequest | null {
  if (!state.target || (state.mode === 'manual' && !state.start)) return null
  return {
    mode: state.mode,
    target: state.target,
    ...(state.mode === 'manual' ? { start: state.start! } : {})
  }
}
