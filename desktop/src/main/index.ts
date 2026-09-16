import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
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
import type {
  AppSettings,
  AppSnapshot,
  GameClient,
  OperationResult,
  PatchRequest,
  ProgressEvent
} from '../shared/types'

const here = path.dirname(fileURLToPath(import.meta.url))
// This utility has no 3D/canvas workload; software rendering avoids a large GPU allocation.
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
let store: Store<{
  settings: AppSettings
  history: OperationResult[]
  confirmed: { request: PatchRequest; installKind: string } | null
  autoUpdatePreferenceRecorded: boolean
}>
const pendingQueries = new Map<string, Promise<unknown>>()

function snapshot(): AppSnapshot {
  return {
    settings: store.get('settings'),
    history: store.get('history'),
    active,
    version: app.getVersion(),
    nextUpdate
  }
}
function send(channel: string, value: unknown) {
  if (window && !window.isDestroyed()) window.webContents.send(channel, value)
}
function refresh() {
  send('app:snapshot', snapshot())
  updateTray()
}
function queryOnce<T>(payload: Record<string, unknown>): Promise<T> {
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
  if (active) throw new Error('已有任务正在执行，请等待完成')
  const request = validateRequest(input)
  const runId = crypto.randomUUID(),
    startedAt = new Date().toISOString(),
    start = Date.now()
  active = { runId, request, startedAt }
  cancellationRequested = false
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
    const client = await queryOnce<GameClient>({
      action: 'inspect',
      gameVersion: request.gameVersion,
      directory: request.gameDirectory,
      language: request.languageMode
    })
    kind = client.installKind
    if (automatic && kind !== store.get('confirmed')?.installKind)
      throw new Error('客户端类型已变化，请重新手动更新')
    if (request.operation === 'update') {
      if (request.patchScope === 'none' && !request.islandRumourHints)
        throw new Error('没有选中任何补丁内容')
      if (
        request.patchScope !== 'none' &&
        !(client.isChina ? request.poeCurrencySeason : request.league)
      )
        throw new Error('请选择价格赛季后再执行')
    }
    if (cancellationRequested) throw new Error('任务已取消，尚未执行补丁')
    report('system', `${client.displayName}\n目标目录：${client.path}\n`)
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
      if (request.gameVersion === 'poe1' &&
          (request.operation === 'localize' || /^__POE_LANGUAGE_MODE__localization\r?$/m.test(stdout))) {
        if (nextState.settings.gameVersion === 'poe1' &&
            path.resolve(nextState.settings.directories.poe1 || '.') === path.resolve(request.gameDirectory))
          nextState.settings = { ...nextState.settings, languageMode: 'localization' }
      }
      if (request.operation === 'update') nextState.confirmed = { request, installKind: kind }
    }
    store.store = nextState
  } catch (error) {
    log.error('保存运行记录失败', error)
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
function schedule() {
  if (!store.get('settings').autoUpdate || !store.get('confirmed')) {
    clearTimeout(timer)
    timer = undefined
    nextUpdate = null
    return
  }
  // Settings changes and manual operations must not postpone an existing hourly check.
  if (timer) return
  nextUpdate = new Date(Date.now() + 3_600_000).toISOString()
  timer = setTimeout(async () => {
    timer = undefined
    nextUpdate = null
    const confirmed = store.get('confirmed')
    if (active || !confirmed || !store.get('settings').autoUpdate) {
      schedule()
      refresh()
      return
    }
    try {
      await runOperation(confirmed.request, true)
    } catch (error) {
      log.error(error)
      schedule()
      refresh()
    }
  }, 3_600_000)
  timer.unref()
}
function showWindow() {
  if (!app.isReady() || !store) return
  if (!window || window.isDestroyed()) createWindow()
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
        enabled: !active && !!store.get('confirmed'),
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
  })
  window.once('ready-to-show', () => {
    if (!process.argv.includes('--hidden')) window?.show()
  })
  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL)
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void window.loadFile(path.join(here, '../renderer/index.html'))
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
  app.on('second-instance', showWindow)
  app
    .whenReady()
    .then(async () => {
      log.initialize()
      log.transports.file.maxSize = 2 * 1024 * 1024
      store = new Store({
        name: 'desktop-settings',
        defaults: {
          settings: defaults,
          history: [] as OperationResult[],
          confirmed: null as { request: PatchRequest; installKind: string } | null,
          autoUpdatePreferenceRecorded: false
        },
        clearInvalidConfig: true
      })
      try {
        store.set('settings', { ...defaults, ...settingsPatch(store.get('settings')) })
      } catch (error) {
        log.error('配置格式无效', error)
        store.set('settings', defaults)
      }
      // v0.7.2 could turn this preference off after a restore without a user action.
      // Migrate that untracked legacy state once; later changes are explicit.
      if (!store.get('autoUpdatePreferenceRecorded')) {
        if (!store.get('settings').autoUpdate && store.get('confirmed'))
          store.set('settings', { ...store.get('settings'), autoUpdate: true })
        store.set('autoUpdatePreferenceRecorded', true)
      }
      session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) =>
        callback(false)
      )
      session.defaultSession.setPermissionCheckHandler(() => false)
      Menu.setApplicationMenu(null)
      handle('app:snapshot', snapshot)
      handle('background:get', getBackground)
      handle('background:choose', () => chooseBackground(window!))
      handle('background:clear', clearBackground)
      handle('settings:save', (input: unknown) => {
        const patch = settingsPatch(input)
        if (active && Object.keys(patch).some((key) => key !== 'autoUpdate'))
          throw new Error('任务执行中不能修改设置')
        if (patch.autoStart !== undefined) {
          if (!app.isPackaged) throw new Error('开机启动仅在发布版本中可用')
          app.setLoginItemSettings({
            openAtLogin: patch.autoStart,
            path: process.env.PORTABLE_EXECUTABLE_FILE || app.getPath('exe'),
            args: ['--hidden']
          })
        }
        if (patch.autoUpdate !== undefined) store.set('autoUpdatePreferenceRecorded', true)
        store.set('settings', { ...store.get('settings'), ...patch })
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
      createWindow()
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
    clearTimeout(timer)
    void Promise.allSettled([...workers].map(stopTree)).then(() => app.quit())
    return
  }
  quitting = true
  clearTimeout(timer)
})
app.on('window-all-closed', () => {
  if (!active && (!tray || !store.get('settings').closeToTray)) app.quit()
})
