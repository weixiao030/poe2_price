import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  powerMonitor,
  session,
  shell,
  Tray
} from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs/promises'
import crypto from 'node:crypto'
import type { ChildProcessWithoutNullStreams } from 'node:child_process'
import log from 'electron-log/main'
import Store from 'electron-store'
import {
  appendTail,
  argsFor,
  boolean,
  choice,
  defaults,
  scriptFor,
  settingsPatch,
  text,
  validateRequest
} from './policy'
import { query, stopTree, worker, workers } from './engine'
import { dataRoot } from './runtime'
import { getBackground, chooseBackground, clearBackground } from './background'
import { cleanupOldFiles } from './maintenance'
import {
  BUSY_RETRY,
  restoreAutoUpdateSchedule,
  restoreConfirmedUpdate,
  scheduleAfterUpdate
} from './auto-update'
import type { AutoUpdateSchedule, ConfirmedUpdate } from './auto-update'
import { reconcileAutoStart, shouldShowSecondInstance } from './startup'
import { SoftwareUpdater } from './software-update'
import { NsisUpdateDriver } from './software-update-driver'
import type { UpdateConfig } from '../shared/software-update'
import type {
  AppSettings,
  AppSnapshot,
  GameClient,
  OperationResult,
  PatchRequest,
  ProgressEvent
} from '../shared/types'

const here = path.dirname(fileURLToPath(import.meta.url))
// This utility does not need hardware acceleration.
app.disableHardwareAcceleration()
if (process.env.POE_DESKTOP_DATA) app.setPath('userData', process.env.POE_DESKTOP_DATA)
let window: BrowserWindow | null = null
let tray: Tray | null = null
let quitting = false
let active: AppSnapshot['active'] = null
let processChild: ChildProcessWithoutNullStreams | null = null
let cancellationRequested = false
let timer: NodeJS.Timeout | undefined
let nextUpdate: string | null = null
let scheduleGeneration = 0
let autoStartStatus = ''
let autoUpdatePausedReason = ''
let pendingShowWindow = false
let maintenanceRunning = false
let softwareUpdater: SoftwareUpdater | undefined
let store: Store<{
  settings: AppSettings
  history: OperationResult[]
  confirmed: ConfirmedUpdate | null
  autoUpdateSchedule: AutoUpdateSchedule | null
}>
const pendingQueries = new Map<string, Promise<unknown>>()

function snapshot(): AppSnapshot {
  return {
    settings: store.get('settings'),
    history: store.get('history'),
    active,
    version: app.getVersion(),
    nextUpdate,
    autoUpdateStatus: autoUpdateStatus(),
    autoStartStatus
  }
}
function send(channel: string, value: unknown) {
  if (window && !window.isDestroyed()) window.webContents.send(channel, value)
}
function refresh() {
  if (window && !window.isDestroyed()) send('app:snapshot', snapshot())
  updateTray()
}
function queryOnce<T>(payload: Record<string, unknown>): Promise<T> {
  if (softwareUpdater?.installing) throw new Error('正在安装软件更新，请稍后重试')
  if (maintenanceRunning) throw new Error('正在清理旧文件，请稍后重试')
  const key = JSON.stringify(payload)
  if (!pendingQueries.has(key)) {
    if (pendingQueries.size >= 4) throw new Error('后台正在处理其他查询，请稍后重试')
    pendingQueries.set(
      key,
      query<T>(payload).finally(() => pendingQueries.delete(key))
    )
  }
  return pendingQueries.get(key) as Promise<T>
}
async function runOperation(input: unknown, automatic = false): Promise<OperationResult> {
  if (softwareUpdater?.installing) throw new Error('正在安装软件更新，请稍后重试')
  if (active) throw new Error('已有任务正在执行，请等待完成')
  if (maintenanceRunning) throw new Error('请等待文件清理完成')
  const request = validateRequest(input)
  if (automatic && request.operation !== 'update') throw new Error('自动任务只允许更新物价')
  const runId = crypto.randomUUID(),
    startedAt = new Date().toISOString(),
    start = Date.now()
  active = { runId, request, startedAt }
  cancellationRequested = false
  schedule()
  refresh()
  const report = (stream: ProgressEvent['stream'], message: string) => {
    if (!message) return
    if (active) active.logTail = appendTail(active.logTail || '', message)
    log.info(`[${runId}][${stream}] ${message}`)
    send('patch:progress', {
      runId,
      stream,
      message,
      at: new Date().toISOString()
    } satisfies ProgressEvent)
  }
  report('system', '正在校验客户端和运行环境…\n')
  let stdout = '',
    stderr = '',
    exitCode = 1,
    kind = ''
  try {
    const confirmed = store.get('confirmed')
    const client = automatic
      ? null
      : await queryOnce<GameClient>({
          action: 'inspect',
          gameVersion: request.gameVersion,
          directory: request.gameDirectory,
          language: request.languageMode
        })
    kind = automatic ? confirmed?.installKind || '' : client!.installKind
    if (automatic && !confirmed) throw new Error('请先完成一次手动更新')
    if (request.operation === 'update') {
      if (request.patchScope === 'none' && !request.islandRumourHints)
        throw new Error('没有选中任何补丁内容')
      if (
        !automatic &&
        request.patchScope !== 'none' &&
        request.leagueMode !== 'auto' &&
        !(client!.isChina ? request.poeCurrencySeason : request.league || request.poeNinjaLeague)
      )
        throw new Error('请选择价格赛季后再执行')
    }
    if (cancellationRequested) throw new Error('任务已取消，尚未执行补丁')
    report(
      'system',
      automatic
        ? `自动更新检查\n目标目录：${request.gameDirectory}\n`
        : `${client!.displayName}\n目标目录：${client!.path}\n`
    )
    const result = await worker(
      {
        action: 'run',
        request,
        automatic,
        arguments: argsFor(request),
        script: scriptFor(request),
        expectedKind: kind
      },
      report,
      (child) => {
        processChild = child
        if (cancellationRequested) void stopTree(child)
      },
      45 * 60_000
    )
    stdout = result.stdout
    stderr = result.stderr
    exitCode = result.exitCode
    if (exitCode === 0 && /^__POE_LANGUAGE_MODE__localization\r?$/m.test(stdout))
      request.languageMode = 'localization'
  } catch (error) {
    stderr = error instanceof Error ? error.message : String(error)
    report('stderr', stderr + '\n')
  } finally {
    processChild = null
  }
  const result: OperationResult = {
    runId,
    operation: request.operation,
    gameVersion: request.gameVersion,
    gameDirectory: request.gameDirectory,
    exitCode,
    cancelled: cancellationRequested,
    skipped: automatic && exitCode === 2,
    stdout,
    stderr,
    startedAt,
    durationMs: Date.now() - start,
    automatic
  }
  try {
    const nextState = store.store
    nextState.history = [
      { ...result, stdout: stdout.slice(-16_000), stderr: stderr.slice(-16_000) },
      ...nextState.history
    ].slice(0, 50)
    if (exitCode === 0 && !cancellationRequested) {
      if (
        request.gameVersion === 'poe1' &&
        (request.operation === 'localize' || /^__POE_LANGUAGE_MODE__localization\r?$/m.test(stdout))
      ) {
        if (
          nextState.settings.gameVersion === 'poe1' &&
          path.resolve(nextState.settings.directories.poe1 || '.') ===
            path.resolve(request.gameDirectory)
        )
          nextState.settings = { ...nextState.settings, languageMode: 'localization' }
      }
      if (request.operation === 'update')
        nextState.confirmed = { request, installKind: kind, successAt: new Date().toISOString() }
    }
    nextState.autoUpdateSchedule =
      scheduleAfterUpdate(nextState.autoUpdateSchedule, result, Date.now()) ?? null
    store.store = nextState
  } catch (error) {
    log.error('保存运行记录失败', error)
    autoUpdatePausedReason = '保存运行记录失败，自动更新已暂停；请检查磁盘空间后重新开启自动更新。'
    report('stderr', '无法保存运行记录，请检查磁盘空间。\n')
  }
  active = null
  schedule()
  refresh()
  report(
    'system',
    `${result.cancelled ? '已取消，请确认游戏文件完整性' : result.skipped ? '本轮已跳过' : exitCode === 0 ? '操作完成' : `操作失败，退出码 ${exitCode}`}\n`
  )
  return result
}
function cancelSchedule() {
  clearTimeout(timer)
  timer = undefined
  nextUpdate = null
  scheduleGeneration++
}
function autoUpdateStatus(): string {
  if (!store.get('settings').autoUpdate) return '自动更新已关闭。'
  if (autoUpdatePausedReason) return autoUpdatePausedReason
  if (!store.get('confirmed')) return '等待首次手动更新成功，以确认游戏目录和更新配置。'
  if (active) return '任务正在执行，完成后继续安排自动更新。'
  const reason = store.get('autoUpdateSchedule')?.reason
  if (reason === 'game') return '游戏运行或目录占用，每 2 分钟重查；本轮未下载或写入补丁。'
  if (reason === 'busy') return '后台任务占用，1 分钟后重查。'
  if (reason === 'retry') return '上次更新失败，按 1、5、15 分钟间隔重试；详情见运行记录。'
  if (reason === 'cancelled') return '本次任务已取消，5 分钟后重试；关闭开关可停止后续自动更新。'
  return '按上次成功时间每小时更新；启动和休眠恢复后会补做已到期的更新。'
}
function schedule() {
  if (
    quitting ||
    autoUpdatePausedReason ||
    !store.get('settings').autoUpdate ||
    store.get('confirmed')?.request.operation !== 'update' ||
    active
  ) {
    cancelSchedule()
    return
  }
  const saved = store.get('autoUpdateSchedule')
  const plan = restoreAutoUpdateSchedule(
    saved,
    store.get('confirmed'),
    store.get('history'),
    Date.now()
  )!
  if (JSON.stringify(saved) !== JSON.stringify(plan) && !saveAutoUpdateSchedule(plan)) return
  if (timer && nextUpdate === plan.nextAttemptAt) return
  cancelSchedule()
  nextUpdate = plan.nextAttemptAt
  const generation = scheduleGeneration
  // This wake-up only compares timestamps. It does not spawn workers until the persisted deadline.
  const delay = Math.min(60_000, Math.max(1000, Date.parse(nextUpdate) - Date.now()))
  timer = setTimeout(async () => {
    if (generation !== scheduleGeneration || quitting) return
    timer = undefined
    nextUpdate = null
    const confirmed = store.get('confirmed')
    if (confirmed?.request.operation !== 'update' || !store.get('settings').autoUpdate) {
      schedule()
      refresh()
      return
    }
    if (Date.now() < Date.parse(plan.nextAttemptAt)) {
      schedule()
      return
    }
    if (active || maintenanceRunning || softwareUpdater?.installing) {
      saveAutoUpdateSchedule({
        ...plan,
        nextAttemptAt: new Date(Date.now() + BUSY_RETRY).toISOString(),
        reason: 'busy'
      })
      schedule()
      refresh()
      return
    }
    try {
      await runOperation(confirmed.request, true)
    } catch (error) {
      log.error(error)
      saveAutoUpdateSchedule({
        ...plan,
        nextAttemptAt: new Date(Date.now() + 5 * 60_000).toISOString(),
        reason: 'retry'
      })
      schedule()
      refresh()
    }
  }, delay)
  timer.unref()
}
function saveAutoUpdateSchedule(plan: AutoUpdateSchedule): boolean {
  try {
    store.set('autoUpdateSchedule', plan)
    return true
  } catch (error) {
    log.error('保存自动更新计划失败', error)
    autoUpdatePausedReason =
      '保存自动更新计划失败，自动更新已暂停；请检查磁盘空间后重新开启自动更新。'
    cancelSchedule()
    return false
  }
}
function showWindow() {
  if (!app.isReady() || !store) return
  if (!window || window.isDestroyed()) {
    createWindow()
    return
  }
  if (window!.isMinimized()) window!.restore()
  window!.show()
  window!.focus()
}
function updateTray() {
  if (!tray) return
  const last = store.get('history')[0]
  tray.setToolTip(active ? 'POE 物价补丁：任务进行中' : 'POE 物价补丁')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '打开物价补丁', click: showWindow },
      {
        label: active
          ? '任务进行中'
          : last
            ? `最近结果：${last.skipped ? '已跳过' : last.exitCode === 0 && !last.cancelled ? '成功' : '未成功'}`
            : '暂无运行记录',
        enabled: false
      },
      {
        label: '立即自动更新',
        enabled: !active && !maintenanceRunning && !!store.get('confirmed'),
        click: () => {
          const c = store.get('confirmed')
          if (c) void runOperation(c.request, true).catch(log.error)
        }
      },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          if (active) {
            showWindow()
            void dialog.showMessageBox(window!, {
              type: 'info',
              message: '任务仍在执行，请等待完成或在窗口中停止任务。'
            })
          } else {
            quitting = true
            app.quit()
          }
        }
      }
    ])
  )
}
function createWindow() {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) =>
    callback(false)
  )
  session.defaultSession.setPermissionCheckHandler(() => false)
  const icon = app.isPackaged
    ? path.join(process.resourcesPath, 'icon.png')
    : path.join(app.getAppPath(), 'resources/icon.png')
  window = new BrowserWindow({
    width: 1200,
    height: 860,
    minWidth: 820,
    minHeight: 620,
    show: false,
    backgroundColor: '#f6f7f9',
    autoHideMenuBar: true,
    title: 'POE 物价补丁',
    icon,
    webPreferences: {
      preload: path.join(here, '../preload/index.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      spellcheck: false
    }
  })
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.on('render-process-gone', (_event, details) => {
    log.error('Renderer stopped', details)
    if (window && !window.isDestroyed()) window.reload()
  })
  window.on('close', (event) => {
    if (!quitting && (active || store.get('settings').closeToTray)) {
      event.preventDefault()
      // Release the Chromium renderer while the main process keeps the tray and worker.
      window?.destroy()
    }
  })
  window.on('closed', () => {
    window = null
    if (!quitting && !active && !store.get('settings').closeToTray) app.quit()
  })
  const created = window
  created.once('ready-to-show', () => {
    if (!created.isDestroyed()) {
      created.show()
      created.focus()
    }
  })
  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL)
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void window.loadFile(path.join(here, '../renderer/index.html'))
}
function createTray() {
  const icon = app.isPackaged
    ? path.join(process.resourcesPath, 'icon.png')
    : path.join(app.getAppPath(), 'resources/icon.png')
  if (!tray) {
    tray = new Tray(nativeImage.createFromPath(icon).resize({ width: 20, height: 20 }))
    tray.on('double-click', showWindow)
    updateTray()
  }
}
function handle(channel: string, fn: (...args: any[]) => unknown) {
  ipcMain.handle(channel, (event, ...args: unknown[]) => {
    if (
      !window ||
      event.sender !== window.webContents ||
      event.senderFrame !== window.webContents.mainFrame
    )
      throw new Error('拒绝不可信调用')
    return fn(...args)
  })
}
if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', (_event, argv) => {
    if (!shouldShowSecondInstance(argv)) return
    if (!store) pendingShowWindow = true
    else showWindow()
  })
  app
    .whenReady()
    .then(async () => {
      // Renderer output uses our bounded IPC stream; no logging preload is needed.
      log.initialize({ preload: false })
      log.transports.file.maxSize = 2 * 1024 * 1024
      store = new Store({
        name: 'desktop-settings',
        defaults: {
          settings: defaults,
          history: [] as OperationResult[],
          confirmed: null as ConfirmedUpdate | null,
          autoUpdateSchedule: null as AutoUpdateSchedule | null
        },
        clearInvalidConfig: true
      })
      try {
        const saved = store.store
        const confirmed = restoreConfirmedUpdate(saved.confirmed)
        const history = Array.isArray(saved.history)
          ? saved.history
              .filter(
                (item) =>
                  item && typeof item.runId === 'string' && typeof item.gameDirectory === 'string'
              )
              .slice(0, 50)
          : []
        // Keep only active application data when migrating older profiles.
        store.store = {
          settings: { ...defaults, ...settingsPatch(saved.settings) },
          history,
          confirmed,
          autoUpdateSchedule: restoreAutoUpdateSchedule(
            saved.autoUpdateSchedule,
            confirmed,
            history,
            Date.now()
          )
        }
      } catch (error) {
        log.error('配置格式无效', error)
        store.store = { settings: defaults, history: [], confirmed: null, autoUpdateSchedule: null }
      }
      const syncAutoStart = (enabled: boolean) => {
        if (!app.isPackaged) {
          autoStartStatus = '开机启动仅在发布版本中可用。'
          return
        }
        autoStartStatus = reconcileAutoStart(
          app,
          process.env.PORTABLE_EXECUTABLE_FILE || app.getPath('exe'),
          enabled
        )
        log.info(`开机启动检查：${autoStartStatus}`)
      }
      try {
        syncAutoStart(store.get('settings').autoStart)
      } catch (error) {
        autoStartStatus = `开机启动检查失败：${error instanceof Error ? error.message : String(error)}`
        log.error(autoStartStatus)
      }
      Menu.setApplicationMenu(null)
      const softwareResources = app.isPackaged ? process.resourcesPath : path.join(app.getAppPath(), 'resources')
      const updateConfig = JSON.parse(await fs.readFile(path.join(softwareResources, 'update-config.json'), 'utf8')) as UpdateConfig
      const currentRelease = JSON.parse(await fs.readFile(path.join(softwareResources, 'current-release.json'), 'utf8'))
      softwareUpdater = new SoftwareUpdater({
        version: app.getVersion(), notes: currentRelease.notes, config: updateConfig,
        stateRoot: path.join(app.getPath('userData'), 'software-updates'),
        driver: new NsisUpdateDriver(log),
        packaged: app.isPackaged,
        canInstall: () => !active && !pendingQueries.size && !workers.size && !maintenanceRunning,
        changed: state => send('software:state', state)
      })
      await softwareUpdater.previousResult()
      handle('software:ui-ready', () => softwareUpdater!.uiReady())
      handle('software:state', () => softwareUpdater!.snapshot)
      handle('software:check', () => softwareUpdater!.check())
      handle('software:download', () => softwareUpdater!.download())
      handle('software:install', () => softwareUpdater!.install())
      handle('software:cancel', () => softwareUpdater!.cancel())
      handle('app:copy-feedback-group', () => clipboard.writeText('168887742'))
      handle('app:snapshot', snapshot)
      handle('background:get', getBackground)
      handle('background:choose', () => chooseBackground(window!))
      handle('background:clear', clearBackground)
      handle('app:community', (kind: unknown) => {
        const links = {
          source: 'https://github.com/weixiao030/poe2_price',
          community: 'https://www.caimogu.cc/post/2403703.html'
        }
        return shell.openExternal(links[choice(kind, ['source', 'community'])])
      })
      handle('app:cleanup', async (input: unknown, apply: unknown) => {
        const kind = choice(input, ['cache', 'logs']),
          remove = boolean(apply)
        if (active || pendingQueries.size || workers.size || maintenanceRunning || softwareUpdater?.installing)
          throw new Error('后台任务进行中，请等待查询或补丁任务完成')
        maintenanceRunning = true
        try {
          if (remove) {
            const result = await dialog.showMessageBox(window!, {
              type: 'question',
              title: '清理旧文件',
              message: `清理 7 天前的${kind === 'logs' ? '旧日志' : '补丁缓存'}？`,
              detail: '保留最近文件、当前日志、应用配置和所有游戏还原备份。此操作不能撤销。',
              buttons: ['取消', '确认清理'],
              defaultId: 0,
              cancelId: 0
            })
            if (result.response !== 1)
              return { files: 0, bytes: 0, skipped: 0, olderThanDays: 7, cancelled: true }
          }
          return await cleanupOldFiles(
            app.getPath('userData'),
            app.getPath('logs'),
            kind,
            log.transports.file.getFile().path,
            remove
          )
        } finally {
          maintenanceRunning = false
          schedule()
          refresh()
        }
      })
      handle('settings:save', (input: unknown) => {
        const patch = settingsPatch(input)
        if (active && Object.keys(patch).some((key) => key !== 'autoUpdate'))
          throw new Error('任务执行中不能修改设置')
        if (patch.autoStart !== undefined) {
          if (!app.isPackaged) throw new Error('开机启动仅在发布版本中可用')
          try {
            syncAutoStart(patch.autoStart)
          } catch (error) {
            autoStartStatus = String(error)
            refresh()
            throw error
          }
        }
        store.set('settings', { ...store.get('settings'), ...patch })
        if (patch.autoUpdate === true) autoUpdatePausedReason = ''
        if (patch.autoUpdate !== undefined)
          log.info(`用户设置每小时自动更新：${patch.autoUpdate ? '开启' : '关闭'}`)
        schedule()
        refresh()
        return store.get('settings')
      })
      handle('game:pick', async () => {
        const result = await dialog.showOpenDialog(window!, {
          title: '选择游戏根目录',
          properties: ['openDirectory']
        })
        return result.canceled ? null : result.filePaths[0]
      })
      handle('game:discover', (version: unknown) =>
        queryOnce({
          action: 'discover',
          gameVersion: choice(version, ['poe1', 'poe2']),
          preferredRoot: path.dirname(app.getPath('exe'))
        })
      )
      handle('game:inspect', (version: unknown, directory: unknown, language: unknown) =>
        queryOnce({
          action: 'inspect',
          gameVersion: choice(version, ['poe1', 'poe2']),
          directory: text(directory),
          language: choice(language, ['auto', 'localization', 'zh-CN', 'zh-TW', 'config'])
        })
      )
      handle('game:leagues', (version: unknown, china: unknown) =>
        queryOnce({
          action: 'leagues',
          gameVersion: choice(version, ['poe1', 'poe2']),
          china: boolean(china)
        })
      )
      handle('patch:run', (request: unknown) => runOperation(request))
      handle('patch:cancel', async (id: unknown) => {
        if (!active || active.runId !== text(id)) return false
        cancellationRequested = true
        return processChild ? stopTree(processChild) : true
      })
      handle('app:folder', async (kind: unknown) => {
        const dir =
          choice(kind, ['logs', 'output']) === 'logs'
            ? app.getPath('logs')
            : path.join(dataRoot(), 'output')
        await fs.mkdir(dir, { recursive: true })
        const error = await shell.openPath(dir)
        if (error) throw new Error(error)
      })
      handle('app:export', async (content: unknown) => {
        if (typeof content !== 'string' || content.length > 500_000) throw new Error('日志大小超限')
        const result = await dialog.showSaveDialog(window!, {
          title: '导出日志',
          defaultPath: `poe-patch-${new Date().toISOString().slice(0, 10)}.txt`,
          filters: [{ name: '文本文件', extensions: ['txt'] }]
        })
        if (result.canceled || !result.filePath) return false
        await fs.writeFile(result.filePath, content, 'utf8')
        return true
      })
      schedule()
      powerMonitor.on('resume', () => {
        cancelSchedule()
        schedule()
        refresh()
      })
      createTray()
      if (pendingShowWindow || !process.argv.includes('--hidden')) createWindow()
      app.on('activate', showWindow)
    })
    .catch((error) => {
      log.error(error)
      dialog.showErrorBox('应用启动失败', String(error))
      app.quit()
    })
}
app.on('before-quit', (event) => {
  if (active) {
    event.preventDefault()
    showWindow()
    return
  }
  if (!quitting && workers.size) {
    event.preventDefault()
    quitting = true
    cancelSchedule()
    void Promise.allSettled([...workers].map(stopTree)).then(() => app.quit())
    return
  }
  quitting = true
  cancelSchedule()
})
app.on('window-all-closed', () => {
  if (!active && (!tray || !store.get('settings').closeToTray)) app.quit()
})
