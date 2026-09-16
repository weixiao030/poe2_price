import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const base = path.resolve(root, '../verification/desktop-v0.7.0/followup-0.7.1')
const output = path.join(base, 'controls')
await fs.mkdir(output, { recursive: true })
const env = { ...process.env, POE_DESKTOP_DATA: path.join(base, 'real-profile') }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ args: [root], env, timeout: 60000 })
let page = await app.firstWindow()
const evidence = { checks: [], results: [], errors: [] }
const request = { operation: 'update', gameVersion: 'poe1', gameDirectory: 'D:\\poe1', patchScope: 'currency', languageMode: 'zh-CN', league: 'Allflame', poeNinjaLeague: 'Allflame', poeCurrencySeason: '', leagueIsCurrent: true, islandRumourHints: false }
const snapshot = () => page.evaluate(() => window.desktop.getSnapshot())
async function waitState(predicate, timeout = 120000) {
  const until = Date.now() + timeout
  while (Date.now() < until) {
    const state = await snapshot()
    if (predicate(state)) return state
    await new Promise((r) => setTimeout(r, 100))
  }
  throw new Error('State timed out')
}
async function result(name, value) {
  evidence.results.push({ name, ...value })
  console.log(name, 'exit', value.exitCode, 'cancelled', value.cancelled, 'skipped', value.skipped)
  await fs.writeFile(path.join(output, `${name}.json`), JSON.stringify(value, null, 2))
}
function readback(label) {
  const dir = path.join(output, label)
  const check = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(root, 'scripts/real-engine-inspect.ps1'), '-GameVersion', 'poe1', '-GameDirectory', 'D:/poe1', '-OutputDirectory', dir], { windowsHide: true, encoding: 'utf8', timeout: 120000 })
  assert.equal(check.status, 0, check.stderr)
  return fs.readFile(path.join(dir, 'extracted-hashes.json'), 'utf8').then((t) => JSON.parse(t.replace(/^\ufeff/, '')).map((r) => [r.entry, r.sha256]))
}
try {
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  page.on('pageerror', (e) => evidence.errors.push(e.message))
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false, autoUpdate: false, gameVersion: 'poe1', patchScope: 'currency', languageMode: 'zh-CN', directories: { poe1: 'D:\\poe1', poe2: 'D:\\poe2' } }))
  await page.reload()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.getByText('目录已识别', { exact: true }).waitFor()
  await page.getByRole('button', { name: '开始更新物价', exact: true }).waitFor()
  await page.waitForFunction(() => !document.querySelector('.persistent-actions .n-button--primary-type').disabled, null, { timeout: 120000 })
  await page.getByRole('button', { name: '开始更新物价', exact: true }).click()
  await page.getByRole('button', { name: '确认执行', exact: true }).click()
  await waitState((s) => s.active)
  const duplicate = await page.evaluate(async (r) => { try { await window.desktop.runOperation(r); return '' } catch(e) { return String(e) } }, request)
  assert.match(duplicate, /已有任务/)
  const state = await waitState((s) => !s.active && s.history[0]?.operation === 'update')
  assert.equal(state.history[0].exitCode, 0)
  assert.equal(state.settings.languageMode, 'localization')
  assert.match(state.history[0].stdout, /__POE_LANGUAGE_MODE__localization/)
  const persisted = JSON.parse(await fs.readFile(path.join(base, 'real-profile/desktop-settings.json'), 'utf8'))
  assert.equal(persisted.confirmed.request.languageMode, 'localization')
  await result('ui-update', state.history[0])
  evidence.checks.push('真实界面确认更新成功；同一时间第二次任务被拒绝')
  await app.evaluate(({ dialog }, destination) => { dialog.showSaveDialog = async () => ({ canceled: false, filePath: destination }) }, path.join(output, 'exported-log.txt'))
  await page.getByRole('button', { name: '导出', exact: true }).click()
  assert.match(await fs.readFile(path.join(output, 'exported-log.txt'), 'utf8'), /POE1/)
  evidence.checks.push('真实更新日志从界面导出为 UTF-8')

  // Advance the actual registered hourly callback; the production worker and game files are unchanged.
  await app.evaluate(() => {
    const original = globalThis.setTimeout
    globalThis.setTimeout = function(callback, delay, ...args) {
      if (delay === 3600000) globalThis.__hourlyCallback = callback
      return original(callback, delay, ...args)
    }
  })
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: true }))
  assert.ok((await snapshot()).nextUpdate)
  await app.evaluate(async () => { await globalThis.__hourlyCallback() })
  const automatic = (await snapshot()).history[0]
  assert.equal(automatic.automatic, true)
  assert.equal(automatic.exitCode, 0)
  assert.equal(automatic.stdout.includes('__POE_LANGUAGE_MODE__'), false)
  assert.equal(automatic.stdout.includes('使用 PoeChinese3'), false)
  await result('automatic-update', automatic)
  evidence.checks.push('实际每小时回调提前触发，生产引擎真实自动更新成功')

  const before = await readback('before-cancel')
  await page.evaluate((r) => { window.__realPending = window.desktop.runOperation(r) }, request)
  const active = (await waitState((s) => s.active)).active
  assert.equal(await page.evaluate((id) => window.desktop.cancelOperation(id), active.runId), true)
  const cancelled = await page.evaluate(() => window.__realPending)
  assert.equal(cancelled.cancelled, true)
  await result('cancel-before-write', cancelled)
  assert.deepEqual(await readback('after-cancel'), before)
  evidence.checks.push('真实任务校验阶段取消；取消前后 GGPK 相关表哈希完全一致')

  evidence.checks.push('按用户要求，不启动游戏；运行中保护未继续做真实游戏进程测试')

  await page.getByRole('button', { name: '还原补丁', exact: true }).click()
  await page.getByRole('button', { name: '确认执行', exact: true }).click()
  await waitState((s) => s.active)
  const restored = await waitState((s) => !s.active && s.history[0]?.operation === 'restore')
  assert.equal(restored.history[0].exitCode, 0)
  assert.equal(restored.settings.autoUpdate, true)
  assert.ok(restored.nextUpdate)
  await result('ui-restore', restored.history[0])
  const baseline = JSON.parse((await fs.readFile(path.join(base, 'real-poe1-baseline/extracted-hashes.json'), 'utf8')).replace(/^\ufeff/, '')).map((r) => [r.entry, r.sha256])
  assert.deepEqual(await readback('after-ui-restore'), baseline)
  evidence.checks.push('固定栏还原按钮真实还原，数据回到干净基线并保持自动更新开关')
  await page.getByRole('button', { name: /运行记录/ }).click()
  await page.locator('.history-row').first().click()
  await page.getByText('运行详情', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(output, 'history-detail.png') })
  const count = (await snapshot()).history.length
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: true }))
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 0)
  await app.evaluate(({ app }) => app.emit('activate'))
  page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  assert.equal((await snapshot()).history.length, count)
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false }))
  evidence.checks.push('真实运行详情可查看，托盘释放窗口后重新打开保留历史')
  assert.deepEqual(evidence.errors, [])
} catch(error) {
  evidence.failure = String(error.stack || error)
  throw error
} finally {
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  await app.close()
}
