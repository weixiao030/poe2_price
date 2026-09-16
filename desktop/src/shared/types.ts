import type {
  AtlasSnapshot,
  AtlasRoute,
  MapStatus,
  RouteRequest,
  OverlayOptions
} from './world-map'
export type GameVersion = 'poe1' | 'poe2'
export type Operation = 'update' | 'restore' | 'localize'
export type PatchScope = 'all' | 'currency' | 'uniques' | 'none'
export type LanguageMode = 'auto' | 'localization' | 'zh-CN' | 'zh-TW' | 'config'
export interface PatchRequest {
  operation: Operation
  gameVersion: GameVersion
  gameDirectory: string
  patchScope: PatchScope
  languageMode: LanguageMode
  league: string
  poeNinjaLeague: string
  poeCurrencySeason: string
  leagueIsCurrent: boolean
  islandRumourHints: boolean
}
export interface GameClient {
  gameVersion: GameVersion
  path: string
  displayName: string
  installKind: string
  isChina: boolean
  language: string
}
export interface LeagueOption {
  Label: string
  Value: string
  ScoutLeague: string
  PoeNinjaLeague: string
  PoeCurrencySeason?: string
  IsCurrent: boolean
  DiscoveryFallback?: boolean
  DiscoveryMessage?: string
}
export interface ProgressEvent {
  runId: string
  stream: 'stdout' | 'stderr' | 'system'
  message: string
  at: string
}
export interface OperationResult {
  runId: string
  operation: Operation
  gameVersion: GameVersion
  gameDirectory: string
  exitCode: number
  cancelled: boolean
  skipped?: boolean
  stdout: string
  stderr: string
  startedAt: string
  durationMs: number
  automatic: boolean
}
export interface AppSettings {
  gameVersion: GameVersion
  directories: Record<GameVersion, string>
  languageMode: LanguageMode
  patchScope: PatchScope
  islandRumourHints: boolean
  autoStart: boolean
  autoUpdate: boolean
  closeToTray: boolean
  theme: 'light' | 'dark' | 'system'
  backgroundOpacity: number
}
export interface AppSnapshot {
  settings: AppSettings
  history: OperationResult[]
  active: { runId: string; request: PatchRequest; startedAt: string; logTail?: string } | null
  version: string
  nextUpdate: string | null
}
export interface DesktopApi {
  getMapStatus(): Promise<MapStatus>
  setMapDirectory(directory: string): Promise<MapStatus>
  setMapEnabled(enabled: boolean): Promise<MapStatus>
  confirmMapConsent(token: string): Promise<MapStatus>
  readMap(reset?: boolean): Promise<AtlasSnapshot>
  searchMap(query: string): Promise<string[]>
  planMapRoute(request: RouteRequest): Promise<AtlasRoute>
  clearMapRoute(): Promise<void>
  setMapOverlay(options: Partial<OverlayOptions>): Promise<MapStatus>
  cleanupFiles(
    kind: 'cache' | 'logs',
    remove: boolean
  ): Promise<{
    files: number
    bytes: number
    skipped: number
    olderThanDays: number
    cancelled?: boolean
  }>
  openCommunity(kind: 'source' | 'community' | 'world-map'): Promise<void>
  getSnapshot(): Promise<AppSnapshot>
  saveSettings(settings: Partial<AppSettings>): Promise<AppSettings>
  pickGameDirectory(): Promise<string | null>
  discoverGames(gameVersion: GameVersion): Promise<GameClient[]>
  inspectGame(
    gameVersion: GameVersion,
    directory: string,
    language: LanguageMode
  ): Promise<GameClient>
  getLeagues(gameVersion: GameVersion, china: boolean): Promise<LeagueOption[]>
  runOperation(request: PatchRequest): Promise<OperationResult>
  cancelOperation(runId: string): Promise<boolean>
  openFolder(kind: 'logs' | 'output'): Promise<void>
  exportLog(text: string): Promise<boolean>
  getBackground(): Promise<string | null>
  chooseBackground(): Promise<string | null>
  clearBackground(): Promise<void>
  onProgress(callback: (event: ProgressEvent) => void): () => void
  onSnapshot(callback: (snapshot: AppSnapshot) => void): () => void
}
