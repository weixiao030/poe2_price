import path from 'node:path'
import type { AppSettings, PatchRequest } from '../shared/types'
export const defaults: AppSettings = {
  gameVersion: 'poe2',
  directories: { poe1: '', poe2: '' },
  languageMode: 'auto',
  patchScope: 'all',
  islandRumourHints: true,
  autoStart: false,
  autoUpdate: false,
  closeToTray: true,
  theme: 'light',
  backgroundOpacity: 20
}
export function text(value: unknown, max = 2048): string {
  if (typeof value !== 'string' || value.length > max || /[\x00-\x1f]/.test(value))
    throw new Error('参数包含无效字符或长度超限')
  return value.trim()
}
export function choice<const T extends string>(value: unknown, allowed: readonly T[]): T {
  if (!allowed.includes(value as T)) throw new Error('不支持的参数值')
  return value as T
}
export function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('参数必须为布尔值')
  return value
}
export function settingsPatch(input: unknown): Partial<AppSettings> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('无效设置')
  const out: Partial<AppSettings> = {}
  for (const [key, value] of Object.entries(input)) {
    switch (key) {
      case 'gameVersion':
        out.gameVersion = choice(value, ['poe1', 'poe2'])
        break
      case 'languageMode':
        out.languageMode = choice(value, ['auto', 'localization', 'zh-CN', 'zh-TW', 'config'])
        break
      case 'patchScope':
        out.patchScope = choice(value, ['all', 'currency', 'uniques', 'none'])
        break
      case 'theme':
        out.theme = choice(value, ['light', 'dark', 'system'])
        break
      case 'backgroundOpacity':
        if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > 60)
          throw new Error('背景浓度应在 0 到 60 之间')
        out.backgroundOpacity = value
        break
      case 'autoStart':
      case 'autoUpdate':
      case 'closeToTray':
      case 'islandRumourHints':
        out[key] = boolean(value)
        break
      case 'directories': {
        const dirs = value as Record<string, unknown>
        if (
          !dirs ||
          typeof dirs !== 'object' ||
          Object.keys(dirs).some((k) => !['poe1', 'poe2'].includes(k))
        )
          throw new Error('无效目录配置')
        out.directories = { poe1: text(dirs.poe1), poe2: text(dirs.poe2) }
        break
      }
      default:
        throw new Error(`未知设置：${key}`)
    }
  }
  return out
}
export function validateRequest(input: unknown): PatchRequest {
  if (!input || typeof input !== 'object') throw new Error('无效任务')
  const r = input as PatchRequest
  const gameVersion = choice(r.gameVersion, ['poe1', 'poe2'])
  const operation = choice(r.operation, ['update', 'restore', 'localize'])
  const gameDirectory = text(r.gameDirectory)
  if (
    !path.win32.isAbsolute(gameDirectory) ||
    gameDirectory.startsWith('\\\\') ||
    gameDirectory.length < 4
  )
    throw new Error('请选择本机游戏根目录')
  if (operation === 'localize' && gameVersion !== 'poe1') throw new Error('汉化仅支持 POE1 国际服')
  return {
    operation,
    gameVersion,
    gameDirectory,
    patchScope: choice(r.patchScope, ['all', 'currency', 'uniques', 'none']),
    languageMode: choice(r.languageMode, ['auto', 'localization', 'zh-CN', 'zh-TW', 'config']),
    league: text(r.league, 160),
    poeNinjaLeague: text(r.poeNinjaLeague, 160),
    poeCurrencySeason: text(r.poeCurrencySeason, 160),
    leagueIsCurrent: boolean(r.leagueIsCurrent),
    islandRumourHints: gameVersion === 'poe2' && boolean(r.islandRumourHints)
  }
}
export function scriptFor(r: PatchRequest): string {
  if (r.operation === 'localize') return 'localize_poe1.ps1'
  return `${r.operation === 'restore' ? 'restore' : 'update'}${r.gameVersion === 'poe1' ? '_poe1' : ''}_price_patch.ps1`
}
export function argsFor(r: PatchRequest): Record<string, string | boolean> {
  const args: Record<string, string | boolean> = {
    [r.gameVersion === 'poe1' ? 'Poe1Dir' : 'Poe2Dir']: r.gameDirectory
  }
  if (r.operation === 'localize') return args
  if (r.gameVersion === 'poe1') args.Poe1LanguageMode = r.languageMode
  if (r.operation === 'update') {
    args.PatchScope = r.patchScope
    args.League = r.league
    args.PoeCurrencySeason = r.poeCurrencySeason
    args.LeagueIsCurrent = r.leagueIsCurrent
    if (r.gameVersion === 'poe2') {
      args.PoeNinjaLeague = r.poeNinjaLeague
      args.IslandRumourHints = r.islandRumourHints
    }
  }
  return args
}
export function appendTail(previous: string, next: string, limit = 160_000): string {
  return (previous + next).slice(-limit)
}
