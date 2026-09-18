import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-league-ui-'))
const output = path.join(root, 'test-results', 'leagues')
await fs.mkdir(output, { recursive: true })
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const errors = []
let app
try {
  app = await electron.launch({ args: [root], env, timeout: 60000 })
  const page = await app.firstWindow()
  page.on('pageerror', (error) => errors.push(error.message))
  await app.evaluate(({ ipcMain, BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000)
    globalThis.__catalogOffline = false
    globalThis.__catalogName = 'New League'
    globalThis.__requests = []
    // Only replace IPC in this disposable process; no game directory is opened.
    ipcMain.removeHandler('game:inspect')
    ipcMain.handle('game:inspect', (_event, version, directory) => ({
      gameVersion: version,
      path: directory,
      displayName: 'Fixture client',
      installKind: 'Fixture',
      isChina: directory.includes('CN'),
      language: 'Chinese'
    }))
    ipcMain.removeHandler('game:leagues')
    ipcMain.handle('game:leagues', (_event, version, china) => {
      if (globalThis.__catalogOffline) throw new Error('Simulated directory outage')
      if (china)
        return [
          {
            Label: '0.5.5',
            Value: '0.5.5',
            ScoutLeague: '',
            PoeNinjaLeague: '',
            PoeCurrencySeason: '0.5.5',
            IsCurrent: true
          }
        ]
      return [
        {
          Label: globalThis.__catalogName,
          Value: globalThis.__catalogName,
          ScoutLeague: 'new-id',
          PoeNinjaLeague: globalThis.__catalogName,
          IsCurrent: true
        },
        {
          Label: 'Old League',
          Value: 'Old League',
          ScoutLeague: 'old-id',
          PoeNinjaLeague: 'Old League',
          IsCurrent: false
        }
      ]
    })
    ipcMain.removeHandler('patch:run')
    ipcMain.handle('patch:run', (_event, request) => {
      globalThis.__requests.push(request)
      return {
        runId: 'fixture',
        ...request,
        exitCode: 0,
        cancelled: false,
        stdout: '',
        stderr: '',
        startedAt: new Date().toISOString(),
        durationMs: 0,
        automatic: false
      }
    })
  })
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.evaluate(() =>
    window.desktop.saveSettings({
      closeToTray: false,
      autoUpdate: false,
      gameVersion: 'poe2',
      directories: { poe1: 'D:\\Fixture\\POE1', poe2: 'D:\\Fixture\\POE2' }
    })
  )
  await page.reload()
  await page.getByText('目录已识别', { exact: true }).waitFor()
  await page
    .locator('#league')
    .getByText('自动跟随最新赛季（New League）', { exact: true })
    .waitFor()
  async function select(label) {
    await page.locator('#league').click()
    await page.locator('.n-base-select-option').filter({ hasText: label }).click()
  }
  async function run() {
    const count = await app.evaluate(() => globalThis.__requests.length)
    await page.getByRole('button', { name: '开始更新物价', exact: true }).click()
    await page.getByRole('button', { name: '确认执行', exact: true }).click()
    await page.locator('.n-dialog').waitFor({ state: 'detached' })
    assert.equal(await app.evaluate(() => globalThis.__requests.length), count + 1)
  }
  await select('Old League')
  await page.locator('#league').getByText('Old League', { exact: true }).waitFor()
  assert.equal(
    (await page.evaluate(() => window.desktop.getSnapshot())).settings.leagueSelections?.[
      'poe2-international'
    ]?.mode,
    'fixed'
  )
  await page.reload()
  await page.locator('#league').getByText('Old League', { exact: true }).waitFor()
  await app.evaluate(() => {
    globalThis.__catalogOffline = true
  })
  await page.getByRole('button', { name: '刷新赛季', exact: true }).click()
  await page.getByText('赛季列表刷新失败，已保留当前选择。', { exact: true }).waitFor()
  await run()
  let request = await app.evaluate(() => globalThis.__requests.at(-1))
  assert.equal(request.leagueMode, 'fixed')
  assert.equal(request.league, 'old-id')
  await select('自动跟随最新赛季')
  await app.evaluate(() => {
    globalThis.__catalogOffline = false
    globalThis.__catalogName = 'Next League'
  })
  await page.getByRole('button', { name: '刷新赛季', exact: true }).click()
  await page
    .locator('#league')
    .getByText('自动跟随最新赛季（Next League）', { exact: true })
    .waitFor()
  await run()
  request = await app.evaluate(() => globalThis.__requests.at(-1))
  assert.equal(request.leagueMode, 'auto')
  assert.equal(request.poeNinjaLeague, 'Next League')
  await page.screenshot({ path: path.join(output, 'automatic-desktop.png'), fullPage: true })
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(860, 680))
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  await page.screenshot({ path: path.join(output, 'automatic-compact.png'), fullPage: true })
  await page.evaluate(() =>
    window.desktop.saveSettings({
      directories: { poe1: 'D:\\Fixture\\POE1', poe2: 'D:\\Fixture\\CN' }
    })
  )
  await page.reload()
  await page.locator('#league').getByText('自动跟随最新赛季（0.5.5）', { exact: true }).waitFor()
  await run()
  request = await app.evaluate(() => globalThis.__requests.at(-1))
  assert.equal(request.leagueMode, 'auto')
  assert.equal(request.poeCurrencySeason, '0.5.5')
  assert.equal(request.league, '')
  assert.equal(request.poeNinjaLeague, '')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: 9, profile, screenshots: output, gameFilesTouched: false }))
} catch (error) {
  if (app) {
    const page = await app.firstWindow()
    console.error(
      JSON.stringify({
        snapshot: await page.evaluate(() => window.desktop.getSnapshot()),
        text: await page.locator('body').innerText(),
        errors
      })
    )
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  }
  throw error
} finally {
  await app?.close()
}
