import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const reportDir = path.join(root, 'test-results')
await fs.mkdir(reportDir, { recursive: true })
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-desktop-qa-'))
const userData = path.join(sandbox, 'settings')
const game = path.join(sandbox, '中文目录 $保留', 'Path of Exile 2')
await fs.mkdir(path.join(game, 'Bundles2'), { recursive: true })
await fs.writeFile(path.join(game, 'Bundles2/_.index.bin'), 'offline-fixture-only')
const evidence = { sandbox, checks: [], metrics: {}, errors: [] }
const start = Date.now()
const env = { ...process.env, POE_DESKTOP_DATA: userData }
delete env.ELECTRON_RUN_AS_NODE
let app
async function waitSnapshot(page, predicate, timeout = 30000) {
  const until = Date.now() + timeout
  while (Date.now() < until) {
    const value = await page.evaluate(() => window.desktop.getSnapshot())
    if (predicate(value)) return value
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Snapshot condition timed out')
}
async function launch() {
  app = await electron.launch({ args: [root], env, timeout: 30_000 })
  const page = await app.firstWindow()
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000)
  )
  page.on('pageerror', (error) => evidence.errors.push(error.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  return page
}
try {
  let page = await launch()
  evidence.metrics.startupMs = Date.now() - start
  evidence.checks.push('真实 Electron 冷启动与沙箱 preload 成功')
  assert.equal(await page.evaluate(() => typeof window.require), 'undefined')
  await page.screenshot({ path: path.join(reportDir, 'workspace-light.png'), fullPage: true })
  assert.equal(
    await page.getByRole('button', { name: '开始更新物价', exact: true }).isDisabled(),
    true
  )
  evidence.checks.push('未选择客户端时阻止更新')
  await page.getByRole('button', { name: '运行记录', exact: true }).click()
  await page.getByText('还没有运行记录，完成一次更新后会显示在这里。').waitFor()
  await page.getByRole('button', { name: '应用设置', exact: true }).click()
  await page.getByText('外观与后台运行', { exact: true }).waitFor()
  await page.getByRole('switch', { name: '关闭窗口后保留托盘' }).click()
  assert.equal(
    (await page.evaluate(() => window.desktop.getSnapshot())).settings.closeToTray,
    false
  )
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'dark' }))
  await page.locator('.theme-root.dark').waitFor()
  await page.getByRole('button', { name: '物价补丁', exact: true }).click()
  await page.screenshot({ path: path.join(reportDir, 'workspace-dark.png'), fullPage: true })
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'light' }))
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(860, 680))
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    true
  )
  await page.screenshot({ path: path.join(reportDir, 'workspace-compact.png'), fullPage: true })
  evidence.checks.push('浅色/深色切换，860px 紧凑布局，无横向溢出')
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 800))
  const client = await page.evaluate((dir) => window.desktop.inspectGame('poe2', dir, 'auto'), game)
  assert.equal(client.gameVersion, 'poe2')
  assert.equal(client.path, game)
  evidence.checks.push('真实 PowerShell worker 识别中文及美元符号目录；引擎首次校验释放成功')
  const invalid = await page.evaluate(async () => {
    try {
      await window.desktop.saveSettings({ executable: 'cmd.exe' })
      return false
    } catch {
      return true
    }
  })
  assert.equal(invalid, true)
  const request = {
    operation: 'update',
    gameVersion: 'poe2',
    gameDirectory: path.join(sandbox, 'missing'),
    patchScope: 'all',
    languageMode: 'auto',
    league: 'Fixture',
    poeNinjaLeague: 'Fixture',
    poeCurrencySeason: '',
    leagueIsCurrent: false,
    islandRumourHints: true
  }
  let result = await page.evaluate((r) => window.desktop.runOperation(r), request)
  assert.equal(result.exitCode, 1)
  assert.ok(result.stderr.length)
  evidence.checks.push('错误目录失败可见，任务锁释放，保存失败记录')
  // Only replace a disposable user-data engine script; production sources remain intact.
  const fixtureScript =
    '\ufeffparam([string]$Poe2Dir,[string]$PatchScope,[string]$League,[string]$PoeNinjaLeague,[string]$PoeCurrencySeason,[bool]$LeagueIsCurrent,[switch]$IslandRumourHints,[switch]$SkipGameDirectoryMutex)\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\nWrite-Output "中文开始：$League|$LeagueIsCurrent|$IslandRumourHints"\nStart-Sleep -Seconds 2\nWrite-Output "中文完成"\nexit 0\n'
  await fs.writeFile(path.join(userData, 'engine/tools/update_price_patch.ps1'), fixtureScript)
  request.gameDirectory = game
  await app.evaluate(({ dialog }) => {
    dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
  })
  await page.evaluate((dir) => window.desktop.setMapDirectory(dir), game)
  await page.evaluate(async () => {
    const status = await window.desktop.setMapEnabled(true)
    if (status.consentToken) await window.desktop.confirmMapConsent(status.consentToken)
  })
  await page.evaluate((r) => {
    window.__qaTask = window.desktop.runOperation(r)
  }, request)
  await page.waitForFunction(() => document.body.innerText.includes('任务执行中'))
  const concurrentMap = await page.evaluate(() => window.desktop.readMap())
  assert.equal(
    concurrentMap.available,
    false,
    'fixture has no game process; map worker still responds'
  )
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).enabled, true)
  const duplicate = await page.evaluate(async (r) => {
    try {
      await window.desktop.runOperation(r)
      return false
    } catch {
      return true
    }
  }, request)
  assert.equal(duplicate, true)
  result = await page.evaluate(() => window.__qaTask)
  assert.equal(result.exitCode, 0)
  assert.ok(result.stdout.includes('中文完成'))
  assert.ok(result.stdout.includes('False'))
  await page.waitForFunction(() =>
    document.querySelector('[role="log"]').textContent.includes('中文完成')
  )
  const firstId = result.runId
  result = await page.evaluate((r) => window.desktop.runOperation(r), request)
  assert.notEqual(result.runId, firstId)
  assert.equal(result.exitCode, 0)
  evidence.checks.push(
    '隔离脚本成功执行、历史赛季 false 保留、中文日志完整、连续任务与互斥验证通过'
  )
  await app.evaluate(() => {
    const original = globalThis.setTimeout
    globalThis.setTimeout = (callback, delay, ...args) => {
      if (delay === 3_600_000) {
        globalThis.__qaHourly = callback
        globalThis.setTimeout = original
      }
      return original(callback, delay, ...args)
    }
  })
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: true }))
  await app.evaluate(() => globalThis.__qaHourly())
  const autoResult = (await page.evaluate(() => window.desktop.getSnapshot())).history[0]
  assert.equal(autoResult.automatic, true)
  assert.equal(autoResult.exitCode, 0)
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).enabled, true)
  evidence.checks.push(
    '地图独立子进程与补丁并行响应；触发真实每小时回调执行自动补丁成功，地图未停止'
  )
  const due = (await page.evaluate(() => window.desktop.getSnapshot())).nextUpdate
  assert.ok(due)
  await page.evaluate(() => window.desktop.saveSettings({ backgroundOpacity: 25 }))
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).nextUpdate, due)
  evidence.checks.push('成功手动任务后每小时调度建立；其他设置不推迟原定时间')
  await app.evaluate(({ dialog }, directory) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [directory] })
  }, game)
  await page.getByRole('button', { name: '选择目录', exact: true }).click()
  await page
    .getByText('目录已识别', { exact: true })
    .waitFor()
    .catch(async (error) => {
      await page.screenshot({ path: path.join(reportDir, 'directory-failure.png'), fullPage: true })
      console.error(await page.locator('body').innerText())
      throw error
    })
  await page.waitForFunction(
    () => !document.querySelector('.persistent-actions .n-button--primary-type').disabled,
    null,
    { timeout: 120_000 }
  )
  await page.getByText('仅通货', { exact: true }).click()
  await page.getByRole('button', { name: '开始更新物价', exact: true }).click()
  await page.getByText('确认更新物价', { exact: true }).waitFor()
  await page.getByRole('button', { name: '确认执行', exact: true }).click()
  await page.waitForFunction(() =>
    document.querySelector('[role="log"]').textContent.includes('中文完成')
  )
  await waitSnapshot(page, (s) => !s.active)
  const uiResult = (await page.evaluate(() => window.desktop.getSnapshot())).history[0]
  assert.equal(uiResult.exitCode, 0)
  await fs.writeFile(
    path.join(userData, 'engine/tools/restore_price_patch.ps1'),
    '\ufeffparam([string]$Poe2Dir)\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\nWrite-Output "隔离还原完成"\nexit 0\n'
  )
  await page.getByRole('button', { name: '还原补丁', exact: true }).click()
  await page.getByText('确认还原补丁', { exact: true }).waitFor()
  await page.getByRole('button', { name: '确认执行', exact: true }).click()
  await waitSnapshot(page, (s) => !s.active && s.history[0]?.operation === 'restore')
  const restored = await page.evaluate(() => window.desktop.getSnapshot())
  assert.equal(restored.history[0].exitCode, 0)
  assert.equal(restored.settings.autoUpdate, true)
  assert.ok(restored.nextUpdate)
  evidence.checks.push(
    '真实界面选择目录、刷新赛季、切换范围、确认更新及还原；还原成功后仍保持每小时自动更新'
  )
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: false }))
  await fs.writeFile(
    path.join(userData, 'engine/tools/update_price_patch.ps1'),
    fixtureScript.replace(
      'Start-Sleep -Seconds 2',
      '$child = Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", "Start-Sleep -Seconds 120" -PassThru\nWrite-Output "CHILD_PID=$($child.Id)"\nStart-Sleep -Seconds 60'
    )
  )
  await page.evaluate((r) => {
    window.__qaTask = window.desktop.runOperation(r)
  }, request)
  await page.waitForFunction(() =>
    document.querySelector('[role="log"]').textContent.includes('CHILD_PID=')
  )
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: true }))
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: false }))
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).nextUpdate, null)
  const active = (await page.evaluate(() => window.desktop.getSnapshot())).active
  assert.equal(await page.evaluate((id) => window.desktop.cancelOperation(id), active.runId), true)
  const cancelled = await page.evaluate(() => window.__qaTask)
  assert.equal(cancelled.cancelled, true)
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).settings.autoUpdate, false)
  const childPid = Number(cancelled.stdout.match(/CHILD_PID=(\d+)/)?.[1])
  assert.ok(childPid > 0)
  assert.throws(() => process.kill(childPid, 0))
  evidence.checks.push('真实进程树取消：PowerShell 及其子进程均退出，结果不误报成功')
  const metrics = await app.evaluate(async ({ app }) =>
    app.getAppMetrics().map((m) => ({
      type: m.type,
      workingSetKB: m.memory.workingSetSize,
      privateKB: m.memory.privateBytes,
      cpu: m.cpu.percentCPUUsage
    }))
  )
  evidence.metrics.processes = metrics
  evidence.metrics.workingSetMB = Math.round(metrics.reduce((a, m) => a + m.workingSetKB, 0) / 1024)
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: true }))
  const closed = page.waitForEvent('close')
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
  await closed
  evidence.metrics.trayProcesses = await app.evaluate(({ app }) =>
    app.getAppMetrics().map((m) => ({
      type: m.type,
      workingSetKB: m.memory.workingSetSize,
      privateKB: m.memory.privateBytes,
      cpu: m.cpu.percentCPUUsage
    }))
  )
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 0)
  await app.evaluate(({ app }) => app.emit('activate'))
  page = await app.firstWindow()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).enabled, true)
  evidence.checks.push('地图会话在关闭到托盘并重新打开后仍保持开启')
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false }))
  evidence.checks.push('关闭到托盘释放窗口；托盘重新打开成功，任务历史保留')
  await page.screenshot({ path: path.join(reportDir, 'execution-fixture.png'), fullPage: true })
  await page.getByRole('button', { name: /运行记录/ }).click()
  await page.screenshot({ path: path.join(reportDir, 'history.png'), fullPage: true })
  const count = (await page.evaluate(() => window.desktop.getSnapshot())).history.length
  await page.evaluate(() => window.desktop.saveSettings({ autoUpdate: true }))
  await app.close()
  app = null
  page = await launch()
  const resumed = await page.evaluate(() => window.desktop.getSnapshot())
  assert.equal(resumed.settings.autoUpdate, true)
  assert.ok(resumed.nextUpdate)
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).history.length, count)
  assert.equal(
    (await page.evaluate(() => window.desktop.getSnapshot())).settings.closeToTray,
    false
  )
  await page.getByRole('button', { name: '应用设置', exact: true }).click()
  assert.equal(
    await page.getByRole('switch', { name: '每小时自动更新' }).getAttribute('aria-checked'),
    'true'
  )
  await page.getByRole('switch', { name: '每小时自动更新' }).click()
  await app.close()
  app = null
  page = await launch()
  const disabled = await page.evaluate(() => window.desktop.getSnapshot())
  assert.equal(disabled.settings.autoUpdate, false)
  assert.equal(disabled.nextUpdate, null)
  evidence.checks.push('自动更新开启后重启保持开启并恢复调度；手动关闭后重启保持关闭；历史保留')
  assert.deepEqual(evidence.errors, [])
  evidence.checks.push('所有页面无未捕获 JavaScript 错误')
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  if (app && evidence.checks.length < 12) {
    const page = app.windows()[0]
    if (page && !page.isClosed())
      console.error(
        await page
          .locator('body')
          .innerText()
          .catch(() => '')
      )
  }
  await fs.writeFile(
    path.join(reportDir, 'desktop-evidence.json'),
    JSON.stringify(evidence, null, 2)
  )
  if (app) {
    const p = app.windows()[0]
    if (p && !p.isClosed()) {
      const state = await p.evaluate(() => window.desktop.getSnapshot()).catch(() => null)
      if (state?.active) {
        await p
          .evaluate((id) => window.desktop.cancelOperation(id), state.active.runId)
          .catch(() => {})
        await waitSnapshot(p, (s) => !s.active, 15000).catch(() => {})
      }
    }
    await app.close()
  }
}
