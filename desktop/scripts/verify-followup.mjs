import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const packaged = process.argv.includes('--packaged')
const output = path.resolve(root, `../verification/desktop-v0.7.0/followup-0.7.1/${packaged ? 'packaged-ui' : 'ui'}`)
await fs.mkdir(output, { recursive: true })
const profile = path.join(output, 'profile')
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const evidence = { checks: [], errors: [], screenshots: [] }
const source = path.join(output, '背景 测试.png')
const svg = Buffer.from('<svg width="3200" height="1800" xmlns="http://www.w3.org/2000/svg"><rect width="3200" height="1800" fill="#164966"/><path d="M0 1700L900 360L2000 1500L2500 600L3200 1600V1800H0" fill="#a88259"/><circle cx="2500" cy="380" r="170" fill="#f4d194"/></svg>')
await sharp(svg).png().toFile(source)
await sharp(svg).jpeg().toFile(path.join(output, 'background.jpg'))
await sharp(svg).webp().toFile(path.join(output, 'unsupported.webp'))
await fs.writeFile(path.join(output, 'invalid.png'), 'invalid-image')
await fs.writeFile(path.join(output, 'large.png'), Buffer.alloc(21 * 1024 * 1024))
let app, page
async function launch() {
  app = await electron.launch({ ...(packaged ? { executablePath: path.join(root, 'dist/win-unpacked/POE 物价补丁.exe'), args: [] } : { args: [root] }), env, timeout: 60000 })
  page = await app.firstWindow()
  page.on('pageerror', (e) => evidence.errors.push(e.message))
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
}
async function choose(file) {
  await app.evaluate(({ dialog }, file) => { dialog.showOpenDialog = async () => ({ canceled: !file, filePaths: file ? [file] : [] }) }, file)
}
async function shot(name) {
  const file = path.join(output, `${name}.png`)
  await page.waitForTimeout(180)
  await page.screenshot({ path: file })
  evidence.screenshots.push(file)
}
async function settings() { await page.getByRole('button', { name: '应用设置', exact: true }).click() }
async function workspace() { await page.getByRole('button', { name: '物价补丁', exact: true }).click() }
async function waitFor(predicate) {
  const until = Date.now() + 60000
  while (Date.now() < until) {
    if (await predicate()) return
    await new Promise((r) => setTimeout(r, 100))
  }
  throw new Error('Timed out waiting for UI state')
}
try {
  await launch()
  await page.evaluate(() => window.desktop.clearBackground())
  await page.reload()
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page.evaluate(() => window.desktop.saveSettings({ closeToTray: false, autoUpdate: false, theme: 'light' }))
  for (const [width, height] of [[1200, 860], [860, 680], [820, 620]]) {
    await app.evaluate(({ BrowserWindow }, [w, h]) => BrowserWindow.getAllWindows()[0].setSize(w, h), [width, height])
    const restore = page.getByRole('button', { name: '还原补丁', exact: true })
    const bounds = await restore.boundingBox(), viewport = await page.evaluate(() => ({ w: innerWidth, h: innerHeight }))
    assert.ok(bounds && bounds.y >= 0 && bounds.y + bounds.height <= viewport.h && bounds.x + bounds.width <= viewport.w)
    await shot(`restore-${width}x${height}`)
  }
  evidence.checks.push('还原补丁在默认、紧凑、最小窗口首屏可见，无需滚动')
  assert.equal(await page.getByText('物价工作台', { exact: true }).count(), 0)
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 860))
  await settings()
  await choose(source)
  await page.getByRole('button', { name: '选择背景图片', exact: true }).click()
  await page.locator('.custom-background').waitFor()
  const original = await page.evaluate(() => window.desktop.getBackground())
  assert.ok(original.startsWith('data:image/jpeg;base64,'))
  const dimensions = await sharp(Buffer.from(original.split(',')[1], 'base64')).metadata()
  assert.equal(dimensions.width, 2560)
  await page.evaluate(() => window.desktop.saveSettings({ backgroundOpacity: 45 }))
  await waitFor(async () => await page.locator('.theme-root').evaluate((el) => getComputedStyle(el).getPropertyValue('--background-opacity').trim()) === '0.45')
  await shot('background-settings')
  await workspace()
  await shot('background-light')
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'dark' }))
  await page.locator('.theme-root.dark').waitFor()
  await shot('background-dark')
  await settings()
  await choose(null)
  await page.getByRole('button', { name: '更换背景图片', exact: true }).click()
  assert.equal(await page.evaluate(() => window.desktop.getBackground()), original)
  for (const file of ['invalid.png', 'large.png', 'unsupported.webp']) {
    await choose(path.join(output, file))
    const error = await page.evaluate(async () => { try { await window.desktop.chooseBackground(); return '' } catch(e) { return String(e) } })
    assert.ok(error)
    assert.equal(await page.evaluate(() => window.desktop.getBackground()), original)
    evidence.checks.push(`${file} 被拒绝且保留已有背景：${error}`)
  }
  await choose(path.join(output, 'background.jpg'))
  const jpeg = await page.evaluate(() => window.desktop.chooseBackground())
  assert.ok(jpeg?.startsWith('data:image/jpeg;base64,'))
  evidence.checks.push('真实 PNG、JPEG 解码导入、2560px 限制、取消、坏图和超限保护通过')
  await fs.unlink(source)
  await fs.unlink(path.join(output, 'background.jpg'))
  await app.close()
  await launch()
  assert.equal(await page.evaluate(() => window.desktop.getBackground()), jpeg)
  assert.equal((await page.evaluate(() => window.desktop.getSnapshot())).settings.backgroundOpacity, 45)
  await page.locator('.custom-background').waitFor()
  evidence.checks.push('删除原图片后重启，背景与浓度保持')
  await settings()
  await page.getByRole('button', { name: '恢复默认', exact: true }).click()
  await waitFor(async () => await page.evaluate(() => window.desktop.getBackground()) === null)
  await page.locator('.custom-background').waitFor({ state: 'detached' })
  evidence.checks.push('恢复默认删除导入背景，界面回到默认主题')
  await workspace()
  await page.evaluate(() => window.desktop.saveSettings({ theme: 'light' }))
  await choose('D:\\poe2')
  await page.getByRole('button', { name: /^(选择目录|更换目录)$/ }).click()
  await page.getByText('目录已识别', { exact: true }).waitFor()
  await waitFor(async () => !(await page.getByRole('button', { name: '开始更新物价', exact: true }).isDisabled()))
  await page.getByRole('button', { name: '还原补丁', exact: true }).click()
  await page.getByText('确认还原补丁', { exact: true }).waitFor()
  await shot('restore-confirmation')
  await page.getByRole('button', { name: '返回', exact: true }).click()
  evidence.checks.push('真实 D:\\poe2 目录选择、赛季获取、还原确认弹窗通过')
  await shot('workspace-real-client')
  assert.deepEqual(evidence.errors, [])
  console.log(JSON.stringify(evidence, null, 2))
} catch (error) {
  evidence.failure = String(error.stack || error)
  await shot('failure').catch(() => {})
  throw error
} finally {
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  await app?.close()
}
