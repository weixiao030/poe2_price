import { _electron as electron } from 'playwright'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const directory = process.argv[2]
if (!directory) throw Error('Pass authorized international game directory')
const report = path.join(root, 'test-results')
await fs.mkdir(report, { recursive: true })
const userData = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-overlay-'))
const env = { ...process.env, POE_DESKTOP_DATA: userData }
delete env.ELECTRON_RUN_AS_NODE
const evidence = { checks: [], errors: [] }
const packaged = process.argv.includes('--packaged')
const application = await electron.launch(
  packaged
    ? {
        executablePath: path.join(root, 'dist/win-unpacked/POE 物价补丁.exe'),
        args: ['--hidden'],
        env,
        timeout: 30_000
      }
    : { args: [root, '--hidden'], env, timeout: 30_000 }
)
try {
  const page = await application.firstWindow()
  await application.context().addInitScript(() => {
    globalThis.__atlasPaint = { labels: [], connections: 0 }
    const originalText = CanvasRenderingContext2D.prototype.fillText
    const originalStroke = CanvasRenderingContext2D.prototype.stroke
    const originalClear = CanvasRenderingContext2D.prototype.clearRect
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      globalThis.__atlasPaint = { labels: [], connections: 0 }
      return originalClear.apply(this, args)
    }
    CanvasRenderingContext2D.prototype.fillText = function (...args) {
      globalThis.__atlasPaint.labels.push(args[0])
      return originalText.apply(this, args)
    }
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      if (this.strokeStyle === '#8de2f5c0' || this.strokeStyle === 'rgba(141, 226, 245, 0.753)')
        globalThis.__atlasPaint.connections++
      return originalStroke.apply(this, args)
    }
  })
  await page.getByRole('heading', { name: '物价补丁', exact: true }).waitFor()
  await page
    .getByRole('button', { name: '世界地图规划', exact: true })
    .evaluate((button) => button.click())
  await page.getByText('世界地图读取已关闭', { exact: true }).waitFor()
  await application.evaluate(({ dialog }) => {
    dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
  })
  await page.evaluate((directory) => window.desktop.setMapDirectory(directory), directory)
  await page.evaluate(async () => {
    const status = await window.desktop.setMapEnabled(true)
    if (status.consentToken) await window.desktop.confirmMapConsent(status.consentToken)
  })
  let snapshot = await page.evaluate(() => window.desktop.readMap())
  assert.equal(snapshot.available, true)
  const status = await page.evaluate(() => window.desktop.getMapStatus())
  assert.equal(status.overlay.names, true)
  assert.equal(status.overlay.connections, true)
  const nodes = new Map(snapshot.nodes.map((n) => [n.id, n]))
  const candidate = snapshot.edges.find(
    (e) => nodes.get(`${e.a.x},${e.a.y}`)?.canOpen && !nodes.get(`${e.b.x},${e.b.y}`)?.canOpen
  )
  if (candidate)
    evidence.route = await page.evaluate(
      (target) => window.desktop.planMapRoute({ mode: 'accessible', target }),
      candidate.b
    )
  await application.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()
      .find((w) => w.getTitle() === 'POE 物价补丁')
      .minimize()
  )
  const focus = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      path.join(root, 'scripts/focus-world-map-game.ps1'),
      '-Executable',
      path.join(directory, 'PathOfExile.exe')
    ],
    { encoding: 'utf8', windowsHide: true }
  )
  assert.equal(focus.status, 0, focus.stderr)
  evidence.focus = JSON.parse(focus.stdout.trim())
  let overlay
  for (let i = 0; i < 120; i++) {
    const found = application.windows().find((p) => p.url().includes('overlay.html'))
    const visible = await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().some(
        (w) => w.getTitle() === 'POE2 世界地图覆盖层' && w.isVisible()
      )
    )
    if (found && visible) {
      overlay = found
      break
    }
    await page.waitForTimeout(250)
  }
  assert.ok(overlay, 'overlay window visible above focused game')
  overlay.on('pageerror', (error) => evidence.errors.push(error.message))
  await overlay.waitForTimeout(700)
  const pixels = await overlay.locator('canvas').evaluate((canvas) => {
    const bytes = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let painted = 0,
      transparent = 0
    for (let i = 3; i < bytes.length; i += 4) {
      if (bytes[i] === 0) transparent++
      else painted++
    }
    return { painted, transparent, width: canvas.width, height: canvas.height }
  })
  assert.ok(pixels.painted > 2000)
  assert.ok(pixels.transparent > pixels.painted * 3)
  evidence.pixels = pixels
  evidence.paint = await overlay.evaluate(() => globalThis.__atlasPaint)
  assert.ok(
    evidence.paint.labels.some((text) => /[\u3400-\u9fffA-Za-z]/.test(text)),
    'map names actually drawn'
  )
  assert.ok(evidence.paint.connections > 0, 'connection strokes actually drawn')
  assert.equal(await overlay.evaluate(() => typeof window.desktop), 'undefined')
  assert.equal(await overlay.evaluate(() => typeof window.require), 'undefined')
  await overlay.screenshot({
    path: path.join(report, 'world-map-overlay-transparent.png'),
    omitBackground: true
  })
  snapshot = await page.evaluate(() => window.desktop.readMap())
  evidence.gameWindow = snapshot.gameWindow
  evidence.nodes = snapshot.nodes.length
  evidence.window = await application.evaluate(({ BrowserWindow }) => {
    const w = BrowserWindow.getAllWindows().find((w) => w.getTitle() === 'POE2 世界地图覆盖层')
    return {
      bounds: w.getBounds(),
      focusable: w.isFocusable(),
      alwaysOnTop: w.isAlwaysOnTop(),
      handle: w.getNativeWindowHandle().readBigUInt64LE().toString()
    }
  })
  assert.equal(evidence.window.focusable, false)
  assert.equal(evidence.window.alwaysOnTop, true)
  const nativeCheck = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-Command',
      `Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class OverlayStyleCheck { [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtrW(IntPtr h,int i); }'; [OverlayStyleCheck]::GetWindowLongPtrW([IntPtr]${evidence.window.handle}, -20).ToInt64()`
    ],
    { encoding: 'utf8', windowsHide: true }
  )
  assert.equal(nativeCheck.status, 0, nativeCheck.stderr)
  const style = Number(nativeCheck.stdout.trim())
  assert.ok((style & 0x20) !== 0, 'WS_EX_TRANSPARENT mouse pass-through')
  evidence.clickThrough = true
  delete evidence.window.handle
  evidence.checks.push(
    '游戏前台实际覆盖层可见；透明画布绘制节点；置顶、不抢焦点、WS_EX_TRANSPARENT 鼠标穿透'
  )
  const screenshotSkill = process.env.POE_SCREENSHOT_SCRIPT
  if (screenshotSkill) {
    const destination = path.join(os.tmpdir(), `poe-overlay-capture-${Date.now()}.png`)
    const shot = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        path.join(root, 'scripts/capture-overlay-check.ps1'),
        '-Path',
        destination,
        '-Region',
        `${snapshot.gameWindow.left},${snapshot.gameWindow.top},${snapshot.gameWindow.width},${snapshot.gameWindow.height}`
      ],
      { encoding: 'utf8', windowsHide: true }
    )
    assert.equal(shot.status, 0, shot.stderr)
    evidence.screenshot = shot.stdout.trim().split(/\r?\n/).at(-1)
    await fs.copyFile(evidence.screenshot, path.join(report, 'world-map-overlay-on-game.png'))
  }
  const minimized = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      path.join(root, 'scripts/focus-world-map-game.ps1'),
      '-Executable',
      path.join(directory, 'PathOfExile.exe'),
      '-Minimize'
    ],
    { encoding: 'utf8', windowsHide: true }
  )
  assert.equal(minimized.status, 0, minimized.stderr)
  for (let i = 0; i < 30; i++) {
    const visible = await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().some(
        (w) => w.getTitle() === 'POE2 世界地图覆盖层' && w.isVisible()
      )
    )
    if (!visible) break
    await page.waitForTimeout(200)
  }
  assert.equal(
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows().some(
        (w) => w.getTitle() === 'POE2 世界地图覆盖层' && w.isVisible()
      )
    ),
    false
  )
  spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      path.join(root, 'scripts/focus-world-map-game.ps1'),
      '-Executable',
      path.join(directory, 'PathOfExile.exe')
    ],
    { encoding: 'utf8', windowsHide: true }
  )
  await page.evaluate(() => window.desktop.setMapEnabled(false))
  assert.equal(
    await application.evaluate(
      ({ BrowserWindow }) =>
        BrowserWindow.getAllWindows().filter((w) => w.getTitle() === 'POE2 世界地图覆盖层').length
    ),
    0
  )
  evidence.checks.push('切出游戏自动隐藏；关闭读取销毁覆盖层与只读进程')
  assert.deepEqual(evidence.errors, [])
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await fs.writeFile(
    path.join(report, `world-map-overlay${packaged ? '-packaged' : ''}.json`),
    JSON.stringify(evidence, null, 2)
  )
  await application.close()
}
