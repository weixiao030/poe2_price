import { _electron as electron } from 'playwright'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import assert from 'node:assert/strict'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const candidate = path.resolve(process.argv[2] || path.join(root, 'src/renderer/App.vue'))
const output = path.resolve(
  process.env.LOCALIZE_REPORT_DIR || path.join(root, 'test-results/localize-entry')
)
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-localize-ui-'))
await fs.mkdir(output, { recursive: true })
const source = await fs.readFile(candidate, 'utf8')
await build({
  configFile: false,
  root: path.join(root, 'src/renderer'),
  base: './',
  logLevel: 'error',
  plugins: [
    {
      name: 'localize-candidate',
      enforce: 'pre',
      load(id) {
        if (
          id.replaceAll('\\', '/') === path.join(root, 'src/renderer/App.vue').replaceAll('\\', '/')
        )
          return source
      }
    },
    vue(),
    UnoCSS({ configFile: path.join(root, 'uno.config.ts') })
  ],
  build: { outDir: path.join(sandbox, 'renderer'), emptyOutDir: true }
})
const env = { ...process.env, POE_DESKTOP_DATA: path.join(sandbox, 'profile') }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ args: [root], env, timeout: 30_000 })
const report = { placement: '', checks: [], errors: [] }
try {
  const page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
  // Replace IPC only in this disposable process. Never run the localization tool on a real game.
  await app.evaluate(({ ipcMain, BrowserWindow }, state) => {
    state.settings.gameVersion = 'poe1'
    state.settings.closeToTray = false
    globalThis.__localizeFixture = { state, china: false, calls: [], blockInspect: false }
    const f = globalThis.__localizeFixture
    const send = () => BrowserWindow.getAllWindows()[0].webContents.send('app:snapshot', f.state)
    const handle = (name, fn) => {
      ipcMain.removeHandler(name)
      ipcMain.handle(name, fn)
    }
    handle('app:snapshot', () => f.state)
    handle('settings:save', (_event, patch) => {
      Object.assign(f.state.settings, patch)
      send()
      return f.state.settings
    })
    handle('game:pick', () => 'D:\\Fixture\\POE1')
    handle('game:leagues', () => [])
    handle('game:inspect', async (_event, version, directory) => {
      if (f.blockInspect)
        await new Promise((resolve) => {
          f.finishInspect = resolve
        })
      return {
        gameVersion: version,
        path: directory,
        displayName: 'POE1 国际服',
        installKind: 'standalone',
        isChina: f.china,
        language: 'English'
      }
    })
    handle('patch:run', async (_event, request) => {
      f.calls.push(request)
      f.state.active = { runId: 'fixture', request, startedAt: new Date().toISOString() }
      send()
      await new Promise((resolve) => {
        f.finishRun = resolve
      })
      f.state.active = null
      send()
      return {
        runId: 'fixture',
        operation: request.operation,
        gameVersion: 'poe1',
        gameDirectory: request.gameDirectory,
        exitCode: 0,
        cancelled: false,
        stdout: 'fixture only',
        stderr: '',
        startedAt: new Date().toISOString(),
        durationMs: 1,
        automatic: false
      }
    })
  }, snapshot)
  page.on('pageerror', (error) => report.errors.push(error.message))
  await page.goto(pathToFileURL(path.join(sandbox, 'renderer/index.html')).href)
  const button = page.getByRole('button', { name: /^一键汉化(?: POE1)?$/ })
  await button.waitFor()
  assert.equal(await button.count(), 1)
  report.placement = (await page
    .locator('.scope-field')
    .getByRole('button', { name: /一键汉化/ })
    .count())
    ? 'update-scope'
    : 'persistent-actions'
  if (!process.argv[2]) assert.equal(report.placement, 'persistent-actions')
  assert.equal(
    await page
      .locator('.scope-field')
      .getByRole('button', { name: /一键汉化/ })
      .count(),
    0
  )
  assert.equal(await button.isDisabled(), true)
  report.checks.push('no-client:disabled')
  await page.getByRole('button', { name: '选择目录', exact: true }).click()
  await page.getByText('目录已识别', { exact: true }).waitFor()
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll('button')].find((b) => b.textContent.includes('一键汉化'))
        .disabled
  )
  assert.equal(
    await page.getByRole('button', { name: '开始更新物价', exact: true }).isDisabled(),
    true
  )
  report.checks.push('no-league:localize-enabled,price-update-disabled')
  await button.click()
  await page.getByRole('button', { name: '返回', exact: true }).click()
  assert.equal(await app.evaluate(() => globalThis.__localizeFixture.calls.length), 0)
  report.checks.push('cancel:no-operation')
  await button.click()
  await page.getByRole('button', { name: '确认执行', exact: true }).click()
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll('button')].find((b) => b.textContent.includes('一键汉化'))
        .disabled
  )
  const calls = await app.evaluate(() => globalThis.__localizeFixture.calls)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].operation, 'localize')
  assert.equal(calls[0].league, '')
  assert.equal(calls[0].gameDirectory, 'D:\\Fixture\\POE1')
  report.checks.push('confirm:localize-only;running:disabled')
  await app.evaluate(() => globalThis.__localizeFixture.finishRun())
  await page.getByText('POE1 汉化完成', { exact: true }).waitFor()
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll('button')].find((b) => b.textContent.includes('一键汉化'))
        .disabled
  )
  await app.evaluate(() => {
    globalThis.__localizeFixture.blockInspect = true
  })
  await page.getByRole('button', { name: '更换目录', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.client-path button').disabled)
  report.queryingDisabled = await button.isDisabled()
  if (!process.argv[2]) assert.equal(report.queryingDisabled, true)
  await app.evaluate(() => {
    globalThis.__localizeFixture.blockInspect = false
    globalThis.__localizeFixture.finishInspect()
  })
  await page.waitForFunction(() => !document.querySelector('.client-path button').disabled)
  for (const [width, height] of [
    [1200, 800],
    [860, 680]
  ]) {
    await app.evaluate(
      ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setSize(...size),
      [width, height]
    )
    await button.scrollIntoViewIfNeeded()
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      true
    )
    const localizeBox = await button.boundingBox()
    const restoreBox = await page
      .getByRole('button', { name: '还原补丁', exact: true })
      .boundingBox()
    assert.ok(localizeBox.x + localizeBox.width <= restoreBox.x)
    assert.equal(localizeBox.y, restoreBox.y)
    await page.screenshot({ path: path.join(output, `localize-${width}.png`), fullPage: true })
  }
  assert.equal((await button.innerText()).trim(), '一键汉化 POE1')
  await page
    .locator('.persistent-actions')
    .screenshot({ path: path.join(output, 'localize-actions.png') })
  report.checks.push('desktop-and-compact:no-horizontal-overflow')
  await app.evaluate(() => {
    globalThis.__localizeFixture.china = true
  })
  await page.reload()
  await page.getByText('目录已识别', { exact: true }).waitFor()
  assert.equal(await button.isDisabled(), true)
  report.checks.push('china-client:disabled')
  await page.getByRole('button', { name: 'POE 2', exact: true }).click()
  await button.waitFor({ state: 'hidden' })
  report.checks.push('poe2:hidden')
  assert.deepEqual(report.errors, [])
  console.log(JSON.stringify(report, null, 2))
} finally {
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(report, null, 2))
  await app.close()
}
