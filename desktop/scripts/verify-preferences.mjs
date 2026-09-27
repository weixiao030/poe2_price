// Real Electron controls and on-disk configuration; no renderer or IPC mocks.
import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const version = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8')).version
const report = path.resolve(root, `../verification/preferences-v${version.replaceAll('.', '')}/ui`)
const profile = path.join(report, 'profile')
await fs.mkdir(report, { recursive: true })
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const packaged = process.argv.includes('--packaged')
const errors = [], checks = []
let app
async function waitSaved(page, key, value) {
  const deadline = Date.now() + 10000
  while (Date.now() < deadline) {
    const snapshot = await page.evaluate(() => window.desktop.getSnapshot())
    if (snapshot.settings[key] === value) return
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error(`Setting ${key} was not saved as ${value}`)
}
async function launch() {
  app = await electron.launch({ ...(packaged
    ? { executablePath: path.join(root, 'dist/win-unpacked/物价补丁.exe') }
    : { args: [root] }), env, timeout: 60000 })
  const page = await app.firstWindow()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  page.on('pageerror', error => errors.push(error.message))
  await page.getByRole('heading', { name: '补丁内容', exact: true }).waitFor()
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false }))
  return page
}
async function flip(page, name, key, value) {
  const control = page.getByRole('switch', { name, exact: true })
  if ((await control.getAttribute('aria-checked')) !== String(value)) await control.click()
  await waitSaved(page, key, value)
  assert.equal(await control.getAttribute('aria-checked'), String(value))
}
try {
  let page = await launch()
  await page.getByRole('button', { name: '全部开启', exact: true }).click()
  await waitSaved(page, 'tabletPrices', true)
  for (const [label, scope] of [['通货', 'currency'], ['传奇', 'uniques'], ['岛屿传言提示', 'none'], ['通货与传奇', 'all']]) {
    await page.getByText(label, { exact: true }).click()
    await waitSaved(page, 'patchScope', scope)
    for (const [name, key] of [['碑牌价格', 'tabletPrices'], ['碑牌词缀价格', 'tabletAffixPrices']]) {
      assert.equal(await page.getByRole('switch', { name, exact: true }).isEnabled(), true)
      await flip(page, name, key, false)
      await flip(page, name, key, true)
    }
  }
  checks.push('四种更新范围均可独立开关碑牌价格与词缀，选择自动保存')
  await flip(page, '碑牌价格', 'tabletPrices', false)
  await flip(page, '碑牌词缀价格', 'tabletAffixPrices', false)
  await flip(page, '岛屿传言地图提示', 'islandRumourHints', false)
  assert.equal(await page.getByRole('switch', { name: /每小时自动更新/ }).count(), 0)
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: /^引用设置/ }).click()
  assert.equal(await page.getByRole('switch', { name: '每小时自动更新', exact: true }).count(), 1)
  await flip(page, '每小时自动更新', 'autoUpdate', true)
  const saved = JSON.parse(await fs.readFile(path.join(profile, 'desktop-settings.json'), 'utf8'))
  assert.equal(saved.settings.tabletPrices, false)
  assert.equal(saved.settings.tabletAffixPrices, false)
  assert.equal(saved.settings.islandRumourHints, false)
  checks.push('真实开关点击自动落盘；关闭值没有被默认值覆盖')
  await app.close()
  page = await launch()
  for (const name of ['碑牌价格', '碑牌词缀价格', '岛屿传言地图提示'])
    assert.equal(await page.getByRole('switch', { name, exact: true }).getAttribute('aria-checked'), 'false')
  assert.equal(await page.getByRole('switch', { name: /每小时自动更新/ }).count(), 0)
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: /^引用设置/ }).click()
  assert.equal(await page.getByRole('switch', { name: '每小时自动更新', exact: true }).getAttribute('aria-checked'), 'true')
  checks.push('关闭并重新启动真实应用后完整恢复用户选择')
  await page.locator('.settings-row').filter({ has: page.getByRole('switch', { name: '每小时自动更新', exact: true }) }).screenshot({ path: path.join(report, 'auto-update-settings.png'), animations: 'disabled' })
  await flip(page, '每小时自动更新', 'autoUpdate', false)
  checks.push('每小时自动更新仅在引用设置中显示，开关与持久化正常')
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: /^物价补丁/ }).click()
  await page.getByRole('button', { name: '全部开启', exact: true }).click()
  await waitSaved(page, 'tabletAffixPrices', true)
  await page.getByRole('switch', { name: '碑牌词缀价格', exact: true }).getAttribute('aria-checked')
  for (const [name, width, height, theme] of [
    ['desktop', 1200, 860, 'light'], ['compact', 860, 680, 'light'], ['dark', 1200, 860, 'dark']
  ]) {
    await app.evaluate(({ BrowserWindow }, { width, height }) => BrowserWindow.getAllWindows()[0].setSize(width, height), { width, height })
    await page.evaluate(theme => window.desktop.saveSettings({ theme }), theme)
    await page.locator(theme === 'dark' ? '.theme-root.dark' : '.theme-root:not(.dark)').waitFor()
    await page.evaluate(() => document.querySelector('.page-body').scrollTo(0, 0))
    await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor({ state: 'visible' })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.screenshot({ path: path.join(report, `${name}.png`), animations: 'disabled' })
    await page.locator('.tablet-options').screenshot({ path: path.join(report, `${name}-options.png`), animations: 'disabled' })
  }
  checks.push('浅色、深色和紧凑窗口截图及横向溢出检查')
  assert.deepEqual(errors, [])
  await fs.writeFile(path.join(report, 'result.json'), JSON.stringify({ packaged, checks, errors, passed: true }, null, 2))
  console.log(JSON.stringify({ report, checks, passed: true }))
} finally { if (app) await app.close() }
