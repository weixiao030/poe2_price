export type GameVersion = 'poe1' | 'poe2'
export type Operation = 'update' | 'restore' | 'localize'
export type PatchScope = 'all' | 'currency' | 'uniques' | 'none'
export type LanguageMode = 'auto' | 'localization' | 'zh-CN' | 'zh-TW' | 'config'
export type LeagueMode = 'auto' | 'fixed'
export type LeagueScope = `${GameVersion}-${'china' | 'international'}`
export interface LeaguePreference {
  mode: LeagueMode
  option?: LeagueOption
}
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
  leagueMode?: LeagueMode
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
  tabletAffixes?: import('./operation-outcome').TabletLayerStatus
  wholeTablets?: import('./operation-outcome').TabletLayerStatus
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
  leagueSelections?: Partial<Record<LeagueScope, LeaguePreference>>
}
export interface AppSnapshot {
  settings: AppSettings
  history: OperationResult[]
  active: { runId: string; request: PatchRequest; startedAt: string; logTail?: string } | null
  version: string
  nextUpdate: string | null
  autoUpdateStatus: string
  autoStartStatus: string
}
export interface DesktopApi {
  getSoftwareUpdate(): Promise<import('./software-update').SoftwareUpdateState>
  checkSoftwareUpdate(): Promise<import('./software-update').SoftwareUpdateState>
  dismissSoftwareUpdateNotice(version: string, ignore: boolean): Promise<void>
  downloadSoftwareUpdate(): Promise<import('./software-update').SoftwareUpdateState>
  installSoftwareUpdate(): Promise<import('./software-update').SoftwareUpdateState>
  cancelSoftwareUpdate(): Promise<void>
  copyFeedbackGroup(): Promise<void>
  softwareUiReady(): Promise<void>
  onSoftwareUpdate(callback: (state: import('./software-update').SoftwareUpdateState) => void): () => void
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
  openCommunity(kind: 'source' | 'community'): Promise<void>
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
