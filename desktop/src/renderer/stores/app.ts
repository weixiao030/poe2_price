import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import type {
  AppSettings,
  AppSnapshot,
  GameClient,
  LeagueOption,
  OperationResult,
  PatchRequest,
  ProgressEvent
} from '../../shared/types'

export const useAppStore = defineStore('app', () => {
  const state = ref<AppSnapshot>({
    settings: {
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
    },
    history: [],
    active: null,
    version: '',
    nextUpdate: null,
    autoUpdateStatus: '',
    autoStartStatus: ''
  })
  const loading = ref(true),
    busy = ref(false),
    error = ref(''),
    querying = ref(false),
    leagueLoading = ref(false)
  const client = ref<GameClient | null>(null),
    clients = ref<GameClient[]>([]),
    leagues = ref<LeagueOption[]>([]),
    selectedLeague = ref<string | null>(null)
  const events = shallowRef<ProgressEvent[]>([])
  const background = ref<string | null>(null)
  const running = computed(() => busy.value || !!state.value.active)
  const settings = computed(() => state.value.settings)
  const directory = computed(() => settings.value.directories[settings.value.gameVersion])
  const league = computed(() => leagues.value.find((x) => x.Value === selectedLeague.value))
  const logText = computed(() => events.value.map((e) => e.message).join(''))
  let generation = 0,
    leagueGeneration = 0,
    flush: ReturnType<typeof setTimeout> | undefined
  let pending: ProgressEvent[] = [],
    detach: (() => void)[] = []
  function push(event: ProgressEvent) {
    pending.push(event)
    // Coalesce output bursts so the renderer updates at most ten times a second.
    if (!flush)
      flush = setTimeout(() => {
        const merged = [...events.value, ...pending]
        let size = 0
        events.value = merged
          .reverse()
          .filter((item) => {
            size += item.message.length
            return size <= 160_000
          })
          .slice(0, 600)
          .reverse()
        pending = []
        flush = undefined
      }, 100)
  }
  function clearLog() {
    clearTimeout(flush)
    flush = undefined
    pending = []
    events.value = []
  }
  async function init() {
    try {
      if (!window.desktop) throw new Error('请通过桌面应用启动，此页面需要本地运行环境。')
      detach = [
        window.desktop.onSnapshot((value) => {
          state.value = value
        }),
        window.desktop.onProgress(push)
      ]
      state.value = await window.desktop.getSnapshot()
      void window.desktop
        .getBackground()
        .then((value) => {
          background.value = value
        })
        .catch((e) => {
          error.value = String(e.message || e)
        })
      if (state.value.active?.logTail)
        push({
          runId: state.value.active.runId,
          stream: 'system',
          message: state.value.active.logTail,
          at: new Date().toISOString()
        })
      if (directory.value)
        void inspect().catch((e) => {
          error.value = String(e.message || e)
        })
    } catch (e) {
      error.value = String((e as Error).message || e)
    } finally {
      loading.value = false
    }
  }
  function dispose() {
    detach.forEach((fn) => fn())
    detach = []
    clearTimeout(flush)
  }
  async function save(patch: Partial<AppSettings>) {
    state.value.settings = await window.desktop.saveSettings(patch)
  }
  async function inspect() {
    const token = ++generation
    ++leagueGeneration
    leagueLoading.value = false
    client.value = null
    leagues.value = []
    selectedLeague.value = null
    error.value = ''
    if (!directory.value) return
    querying.value = true
    try {
      const result = await window.desktop.inspectGame(
        settings.value.gameVersion,
        directory.value,
        settings.value.languageMode
      )
      if (token !== generation) return
      client.value = result
      void refreshLeagues()
    } finally {
      if (token === generation) querying.value = false
    }
  }
  async function discover() {
    querying.value = true
    error.value = ''
    try {
      clients.value = await window.desktop.discoverGames(settings.value.gameVersion)
    } finally {
      querying.value = false
    }
  }
  async function selectDirectory(value: string) {
    querying.value = true
    try {
      const result = await window.desktop.inspectGame(
        settings.value.gameVersion,
        value,
        settings.value.languageMode
      )
      await save({
        directories: { ...settings.value.directories, [settings.value.gameVersion]: result.path }
      })
      ++generation
      ++leagueGeneration
      client.value = result
      leagues.value = []
      selectedLeague.value = null
      error.value = ''
      void refreshLeagues()
    } finally {
      querying.value = false
    }
  }
  async function refreshLeagues() {
    if (!client.value) return
    const token = ++leagueGeneration
    const version = settings.value.gameVersion,
      china = client.value.isChina
    leagueLoading.value = true
    error.value = ''
    try {
      const result = await window.desktop.getLeagues(version, china)
      if (token !== leagueGeneration) return
      leagues.value = result
      selectedLeague.value = result.some((x) => x.Value === selectedLeague.value)
        ? selectedLeague.value
        : result[0]?.Value || null
    } catch (e) {
      if (token === leagueGeneration) {
        error.value = String((e as Error).message || e)
        leagues.value = []
        selectedLeague.value = null
      }
    } finally {
      if (token === leagueGeneration) leagueLoading.value = false
    }
  }
  async function run(operation: PatchRequest['operation']): Promise<OperationResult> {
    if (running.value) throw new Error('已有任务正在执行')
    if (!client.value) throw new Error('请先选择有效的游戏目录')
    clearLog()
    busy.value = true
    error.value = ''
    const request: PatchRequest = {
      operation,
      gameVersion: settings.value.gameVersion,
      gameDirectory: client.value.path,
      languageMode: settings.value.languageMode,
      patchScope: settings.value.patchScope,
      islandRumourHints: settings.value.gameVersion === 'poe2' && settings.value.islandRumourHints,
      league:
        settings.value.gameVersion === 'poe1'
          ? league.value?.PoeNinjaLeague || ''
          : league.value?.ScoutLeague || '',
      poeNinjaLeague: league.value?.PoeNinjaLeague || '',
      poeCurrencySeason: league.value?.PoeCurrencySeason || '',
      leagueIsCurrent: league.value?.IsCurrent ?? true
    }
    try {
      const result = await window.desktop.runOperation(request)
      if (
        result.exitCode === 0 &&
        (operation === 'localize' || request.languageMode !== settings.value.languageMode)
      )
        void inspect().catch((e) => {
          error.value = String(e.message || e)
        })
      return result
    } finally {
      busy.value = false
    }
  }
  return {
    state,
    settings,
    loading,
    error,
    querying,
    leagueLoading,
    client,
    clients,
    leagues,
    selectedLeague,
    league,
    events,
    running,
    directory,
    logText,
    init,
    dispose,
    save,
    inspect,
    discover,
    selectDirectory,
    refreshLeagues,
    run,
    clearLog,
    background
  }
})
