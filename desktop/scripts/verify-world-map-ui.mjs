import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const report = path.join(root, 'test-results')
await fs.mkdir(report, { recursive: true })
const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-map-ui-'))
const userData = path.join(sandbox, 'profile')
const fixture = path.join(sandbox, 'Path of Exile 2')
await fs.mkdir(path.join(fixture, 'Bundles2'), { recursive: true })
await fs.writeFile(path.join(fixture, 'Bundles2/_.index.bin'), 'offline-fixture')
const china = path.join(sandbox, 'CN', 'Path of Exile 2')
await fs.mkdir(path.join(china, 'Bundles2'), { recursive: true })
await fs.writeFile(path.join(china, 'Bundles2/_.index.bin'), 'offline-fixture')
await fs.writeFile(path.join(china, 'wegame.ini'), 'fixture')
await fs.writeFile(path.join(china, 'rail_api64.dll'), 'fixture')
const liveIndex = process.argv.indexOf('--live')
const directory = liveIndex >= 0 ? process.argv[liveIndex + 1] : fixture
const packaged = process.argv.includes('--packaged')
const env = { ...process.env, POE_DESKTOP_DATA: userData }
delete env.ELECTRON_RUN_AS_NODE
const evidence = { checks: [], errors: [], live: liveIndex >= 0, packaged }
let application
async function launch(expectedEnabled = false) {
  application = await electron.launch(
    packaged
      ? {
          executablePath: path.join(root, 'dist/win-unpacked/POE 物价补丁.exe'),
          args: [],
          env,
          timeout: 30_000
        }
      : { args: [root], env, timeout: 30_000 }
  )
  const page = await application.firstWindow()
  await application.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setPosition(-20000, -20000)
  )
  page.on('pageerror', (e) => evidence.errors.push(e.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.getByRole('button', { name: '世界地图规划', exact: true }).click()
  await page.waitForFunction(
    async (expected) => (await window.desktop.getMapStatus()).enabled === expected,
    expectedEnabled,
    { timeout: 60_000 }
  )
  if (!expectedEnabled) await page.getByText('世界地图读取已关闭', { exact: true }).waitFor()
  return page
}
async function dialog(response) {
  await application.evaluate(({ dialog }, value) => {
    globalThis.__mapDialogCount ??= 0
    dialog.showMessageBox = async (_window, options) => {
      globalThis.__mapDialogCount++
      globalThis.__lastMapDialog = options
      return { response: value, checkboxChecked: false }
    }
  }, response)
}
async function rejects(page, expression, value) {
  const error = await page.evaluate(
    async ({ expression, value }) => {
      try {
        await window.desktop[expression](value)
        return ''
      } catch (e) {
        return String(e)
      }
    },
    { expression, value }
  )
  assert.ok(error)
  return error
}
try {
  let page = await launch()
  const initial = await page.evaluate(() => window.desktop.getMapStatus())
  assert.equal(initial.enabled, false)
  assert.equal(initial.authorized, false)
  assert.equal(initial.directory, '')
  assert.equal(initial.overlay.visible, true)
  assert.equal(initial.overlay.names, true)
  assert.equal(initial.overlay.connections, true)
  await rejects(page, 'readMap', false)
  await rejects(page, 'setMapEnabled', true)
  await rejects(page, 'saveSettings', { worldMapEnabled: true })
  await rejects(page, 'setMapDirectory', china)
  evidence.checks.push('默认关闭；未授权无读取；国服目录和通用设置伪造均被后端拒绝')
  await page.screenshot({ path: path.join(report, 'world-map-disabled.png'), fullPage: true })
  await application.evaluate(({ dialog }, directory) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [directory] })
  }, directory)
  await page.getByRole('button', { name: '选择目录', exact: true }).click()
  await page.waitForFunction(
    () =>
      !document
        .querySelector('[aria-label="启用世界地图读取"]')
        .classList.contains('n-switch--disabled')
  )
  await dialog(0)
  await page.getByRole('switch', { name: '启用世界地图读取' }).click()
  const risk = page.getByRole('dialog')
  await risk.getByText('世界地图规划 · 风险确认', { exact: true }).waitFor()
  assert.equal(await risk.getByRole('button', { name: '确认并开启' }).isDisabled(), true)
  await rejects(page, 'readMap', false)
  await rejects(page, 'confirmMapConsent', 'forged-confirmation')
  await page.screenshot({ path: path.join(report, 'world-map-risk-dialog.png'), fullPage: true })
  await risk.getByRole('button', { name: '取消', exact: true }).click()
  await risk.waitFor({ state: 'hidden' })
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).authorized, false)
  const cancelledToken = await page.evaluate(async () => {
    const status = await window.desktop.setMapEnabled(true)
    await window.desktop.setMapEnabled(false)
    return status.consentToken
  })
  await rejects(page, 'confirmMapConsent', cancelledToken)
  evidence.checks.push('应用内风险弹窗；未勾选不能确认；取消不授权；伪造及已取消确认令牌被拒绝')
  await page.getByRole('switch', { name: '启用世界地图读取' }).click()
  await risk.getByRole('checkbox').check()
  await risk.getByRole('button', { name: '确认并开启' }).click()
  await page.waitForFunction(
    () =>
      document.querySelector('[aria-label="启用世界地图读取"]').getAttribute('aria-checked') ===
      'true',
    null,
    { timeout: 60_000 }
  )
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).authorized, true)
  assert.equal(
    await application.evaluate(() => globalThis.__mapDialogCount),
    0,
    'no native authorization dialog'
  )
  await rejects(page, 'confirmMapConsent', cancelledToken)
  await rejects(page, 'cleanupFiles', 'cache')
  if (liveIndex < 0) {
    const nodes = Array.from({ length: 151 }, (_, i) => ({
      id: `${i % 7},${Math.floor(i / 7)}`,
      grid: { x: i % 7, y: Math.floor(i / 7) },
      number: i + 1,
      name: i === 20 ? 'Grand Mirror' : 'Steppe',
      displayName: i === 20 ? '宏偉之鏡' : '草原',
      areaId: 'MapSteppe',
      isHidden: i > 33,
      state: i > 33 ? -2 : i % 4 === 0 ? 1 : i % 3 === 0 ? 0 : 255,
      stateText: i % 4 === 0 ? '可见已开启' : '可见未开启',
      canOpen: i % 4 === 0,
      contentTags: i === 20 ? ['Grand Mirror'] : [],
      contentLabels: i === 20 ? ['宏偉之鏡'] : []
    }))
    const fixtureMap = {
      available: true,
      reason: 'OFFLINE UI FIXTURE',
      nodes,
      edges: nodes.slice(1).map((n, i) => ({ a: nodes[i].grid, b: n.grid })),
      currentNode: nodes[0].grid,
      readMilliseconds: 2,
      capturedAt: new Date().toISOString(),
      unknownNameCount: 0
    }
    // Disposable test process only. Production IPC is exercised above; rendering uses an explicit fixture.
    await application.evaluate(({ ipcMain }, map) => {
      ipcMain.removeHandler('map:read')
      ipcMain.handle('map:read', () => map)
      ipcMain.removeHandler('map:search')
      ipcMain.handle('map:search', (_e, query) =>
        map.nodes
          .filter((n) => String(n.number) === query || n.displayName.includes(query))
          .map((n) => n.id)
      )
      ipcMain.removeHandler('map:route')
      ipcMain.handle(
        'map:route',
        (_e, request) =>
          (map.route = {
            found: true,
            path: [map.nodes[0].grid, request.target],
            distance: 1,
            message: 'OFFLINE UI FIXTURE',
            includePlayerGuide: false
          })
      )
    }, fixtureMap)
  }
  await page.getByRole('button', { name: '重新识别地图布局' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.atlas-result').length > 0, null, {
    timeout: 60_000
  })
  await page.locator('.atlas-result').first().click()
  await page.getByRole('button', { name: '规划路线', exact: true }).click()
  await page.locator('.atlas-route-result').waitFor()
  if (!evidence.live) {
    await page.locator('#atlas-search input').fill('草原')
    await page.waitForFunction(() =>
      document.querySelector('.atlas-search-header').textContent.includes('150 个')
    )
    assert.equal(await page.locator('.atlas-result').count(), 60)
    await page.getByLabel('搜索结果分页').getByText('3', { exact: true }).click()
    assert.equal(await page.locator('.atlas-result').count(), 30)
    assert.match(await page.locator('.atlas-result').first().innerText(), /格.*X/)
    evidence.checks.push('150 条搜索结果全部可分页浏览；距离和相对坐标展示')
  }
  const savedPlanning = {
    query: '保存的搜索',
    mode: 'manual',
    start: { x: 1, y: 2 },
    selected: { x: 3, y: 4 },
    target: { x: 5, y: 6 }
  }
  await page.evaluate((state) => window.desktop.setMapPlanning(state), savedPlanning)
  await page.getByRole('button', { name: '应用设置', exact: true }).click()
  await page.getByRole('button', { name: '世界地图规划', exact: true }).click()
  await page.waitForFunction(
    () => document.querySelector('#atlas-search input')?.value === '保存的搜索'
  )
  assert.deepEqual(
    (await page.evaluate(() => window.desktop.getMapStatus())).planning,
    savedPlanning
  )
  evidence.checks.push('真实主进程保存搜索/目标/手动起点/模式，切页恢复全部状态')
  await page.getByRole('button', { name: '放大地图' }).click()
  assert.equal(await page.locator('.atlas-zoom').innerText(), '130%')
  await page.getByRole('button', { name: '适应全部节点' }).click()
  const pixelColors = await page.locator('canvas').evaluate((canvas) => {
    const colors = new Set(),
      data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    for (let i = 0; i < data.length; i += 16) colors.add(`${data[i]},${data[i + 1]},${data[i + 2]}`)
    return colors.size
  })
  assert.ok(pixelColors > 20, `canvas colors=${pixelColors}`)
  evidence.canvasColors = pixelColors
  await page.screenshot({
    path: path.join(report, `world-map-${evidence.live ? 'live' : 'fixture'}-light.png`),
    fullPage: true
  })
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'dark' }))
  await page.locator('.theme-root.dark').waitFor()
  await page.screenshot({ path: path.join(report, 'world-map-dark.png'), fullPage: true })
  await application.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(860, 720)
  )
  await page.waitForTimeout(300)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: path.join(report, 'world-map-compact.png'), fullPage: true })
  evidence.checks.push('地图画布非空；节点选择、路线、缩放、浅深色和 860px 布局通过')
  const count = await application.evaluate(() => globalThis.__mapDialogCount)
  await page.evaluate(() => window.desktop.setMapEnabled(false))
  await page.evaluate(() => window.desktop.setMapEnabled(true))
  assert.equal(await application.evaluate(() => globalThis.__mapDialogCount), count)
  await page.getByRole('button', { name: '应用设置', exact: true }).click()
  await page.getByText('本软件完全免费开源', { exact: true }).waitFor()
  await page.waitForTimeout(100)
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).enabled, true)
  evidence.checks.push('切换页面后地图后台会话保持开启')
  await page.evaluate(() => window.desktop.setMapEnabled(false))
  const opened = await application.evaluate(({ shell }) => {
    globalThis.__opened = []
    shell.openExternal = async (url) => {
      globalThis.__opened.push(url)
    }
    return true
  })
  assert.ok(opened)
  await page.getByRole('link', { name: 'https://github.com/weixiao030/poe2_price' }).click()
  await page.getByRole('link', { name: 'https://www.caimogu.cc/post/2403703.html' }).click()
  assert.deepEqual(await application.evaluate(() => globalThis.__opened), [
    'https://github.com/weixiao030/poe2_price',
    'https://www.caimogu.cc/post/2403703.html'
  ])
  const oldFile = path.join(userData, 'engine/output/price_patch_cache/old.zip')
  const restoreFile = path.join(userData, 'engine/output/restore/keep.zip')
  for (const file of [oldFile, restoreFile]) {
    await fs.mkdir(path.dirname(file), { recursive: true })
    await fs.writeFile(file, 'protected-fixture')
    const old = new Date(Date.now() - 10 * 86400_000)
    await fs.utimes(file, old, old)
  }
  await dialog(1)
  await page.getByRole('button', { name: '清理旧缓存', exact: true }).click()
  await page.locator('.cleanup-result').waitFor()
  await assert.rejects(fs.access(oldFile))
  await fs.access(restoreFile)
  await page.screenshot({ path: path.join(report, 'settings-maintenance.png'), fullPage: true })
  evidence.checks.push('两处免费开源链接准确；实际清理旧缓存且保留还原文件')
  await application.close()
  application = null
  page = await launch()
  const resumed = await page.evaluate(() => window.desktop.getMapStatus())
  assert.equal(resumed.enabled, false)
  assert.equal(resumed.authorized, true)
  assert.deepEqual(resumed.planning, savedPlanning)
  evidence.checks.push('退出重启后路线工作状态完整恢复')
  await dialog(0)
  await page.evaluate(() => window.desktop.setMapEnabled(true))
  assert.equal(await application.evaluate(() => globalThis.__mapDialogCount), 0)
  await application.close()
  application = null
  page = await launch(true)
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).authorized, true)
  assert.equal(await page.getByRole('dialog').count(), 0)
  const remembered = JSON.parse(
    await fs.readFile(path.join(userData, 'desktop-settings.json'), 'utf8')
  )
  assert.equal(remembered.worldMap.enabled, true)
  await page.evaluate(() => window.desktop.setMapEnabled(false))
  await application.close()
  application = null
  page = await launch(false)
  assert.equal((await page.evaluate(() => window.desktop.getMapStatus())).authorized, true)
  evidence.checks.push('一次授权保留；上次开启则重启自动恢复，上次关闭则保持关闭；恢复不再弹窗')
  assert.deepEqual(evidence.errors, [])
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await fs.writeFile(
    path.join(
      report,
      `world-map-ui-${evidence.live ? 'live' : 'offline'}${packaged ? '-packaged' : ''}.json`
    ),
    JSON.stringify(evidence, null, 2)
  )
  if (application) await application.close()
}
