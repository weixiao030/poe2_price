import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const packaged = process.argv.includes('--packaged')
const output = path.join(root, 'test-results')
await fs.mkdir(output, { recursive: true })
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-startup-check-'))
const config = path.join(profile, 'desktop-settings.json')
const record = {
  runId: 'persisted-run',
  operation: 'update',
  gameVersion: 'poe2',
  gameDirectory: '',
  exitCode: 0,
  cancelled: false,
  stdout: 'preserved history',
  stderr: '',
  startedAt: '2026-09-16T00:00:00Z',
  durationMs: 100,
  automatic: false
}
await fs.writeFile(
  config,
  JSON.stringify({
    settings: {
      gameVersion: 'poe2',
      directories: { poe1: '', poe2: '' },
      languageMode: 'auto',
      patchScope: 'all',
      islandRumourHints: true,
      autoStart: false,
      autoUpdate: true,
      closeToTray: true,
      theme: 'dark',
      backgroundOpacity: 25
    },
    history: [record],
    confirmed: null,
    obsoleteFeature: { enabled: true }
  })
)
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const evidence = { packaged, checks: [], errors: [] }
let application
async function metrics() {
  return application.evaluate(({ app, BrowserWindow }) => ({
    windows: BrowserWindow.getAllWindows().length,
    processes: app
      .getAppMetrics()
      .map((m) => ({
        type: m.type,
        workingSetKB: m.memory.workingSetSize,
        privateKB: m.memory.privateBytes,
        cpu: m.cpu.percentCPUUsage
      }))
  }))
}
async function readyPage() {
  const page = await application.firstWindow()
  page.on('pageerror', (error) => evidence.errors.push(error.message))
  await page.getByRole('button', { name: '开始更新物价', exact: true }).waitFor()
  await page.waitForFunction(() => !document.querySelector('.loading-state'))
  return page
}
try {
  application = await electron.launch({
    ...(packaged ? { executablePath: path.join(root, 'dist/win-unpacked/POE 物价补丁.exe') } : {}),
    args: [...(packaged ? [] : [root]), '--hidden'],
    env,
    timeout: 30000
  })
  await new Promise((resolve) => setTimeout(resolve, 1000))
  evidence.hidden = await metrics()
  assert.equal(evidence.hidden.windows, 0)
  assert.ok(evidence.hidden.processes.every((m) => m.type !== 'Tab'))
  assert.equal(
    await fs.stat(path.join(profile, 'engine')).then(
      () => true,
      () => false
    ),
    false
  )
  const saved = JSON.parse(await fs.readFile(config, 'utf8'))
  assert.deepEqual(Object.keys(saved).sort(), ['confirmed', 'history', 'settings'])
  assert.deepEqual(saved.history, [record])
  assert.equal(saved.settings.autoUpdate, true)
  evidence.checks.push('后台自启零窗口、零渲染进程、不释放引擎；旧配置只保留当前字段与历史')
  const start = performance.now()
  await application.evaluate(({ app }) => app.emit('activate'))
  let page = await readyPage()
  evidence.openFromTrayMs = Math.round(performance.now() - start)
  assert.deepEqual(
    (await page.locator('nav button').allTextContents()).map((x) => x.replace(/\d+$/, '').trim()),
    ['物价补丁', '运行记录', '引用设置']
  )
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined')
  const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
  assert.equal(snapshot.version, '0.8.0')
  assert.deepEqual(snapshot.history, [record])
  assert.equal(snapshot.settings.autoUpdate, true)
  assert.equal(
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
    true
  )
  const allowed = [
    'cleanupFiles',
    'openCommunity',
    'getSnapshot',
    'saveSettings',
    'pickGameDirectory',
    'discoverGames',
    'inspectGame',
    'getLeagues',
    'runOperation',
    'cancelOperation',
    'openFolder',
    'exportLog',
    'getBackground',
    'chooseBackground',
    'clearBackground',
    'onProgress',
    'onSnapshot'
  ]
  assert.deepEqual(await page.evaluate(() => Object.keys(window.desktop).sort()), allowed.sort())
  await page.getByRole('button', { name: '引用设置', exact: true }).click()
  await page.getByRole('heading', { name: '外观与后台运行', exact: true }).waitFor()
  assert.equal(
    await page
      .getByRole('switch', { name: '每小时自动更新', exact: true })
      .getAttribute('aria-checked'),
    'true'
  )
  for (const [width, height] of [
    [1200, 860],
    [820, 620]
  ]) {
    await application.evaluate(
      ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setSize(...size),
      [width, height]
    )
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      true
    )
    await page.screenshot({
      path: path.join(output, `startup-${packaged ? 'packaged' : 'dev'}-${width}.png`)
    })
  }
  await page.getByRole('button', { name: /运行记录/ }).click()
  await page.getByText('运行记录', { exact: true }).last().waitFor()
  evidence.checks.push('导航顺序、版本、IPC 白名单、设置/历史保留、两种窗口尺寸通过')
  const closed = page.waitForEvent('close')
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
  await closed
  await new Promise((resolve) => setTimeout(resolve, 1000))
  evidence.tray = await metrics()
  assert.equal(evidence.tray.windows, 0)
  assert.ok(evidence.tray.processes.every((m) => m.type !== 'Tab'))
  await application.evaluate(({ app }) => app.emit('second-instance'))
  page = await readyPage()
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).history.length, 1)
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].minimize())
  await application.evaluate(({ app }) => app.emit('activate'))
  assert.equal(
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].isMinimized()
    ),
    false
  )
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false }))
  const exited = application.waitForEvent('close')
  await application
    .evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    .catch(() => {})
  await exited
  application = null
  assert.deepEqual(evidence.errors, [])
  evidence.checks.push('关闭到托盘释放渲染进程、再次打开/最小化恢复、关闭退出通过')
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  if (application) await application.close()
  await fs.writeFile(
    path.join(output, `startup-${packaged ? 'packaged' : 'dev'}-evidence.json`),
    JSON.stringify(evidence, null, 2)
  )
}
