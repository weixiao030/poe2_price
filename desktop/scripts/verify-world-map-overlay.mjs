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
async function waitState(page, predicate, timeout = 10000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const state = await page.evaluate(() => window.desktop.getMapStatus())
    if (predicate(state)) return state
    await page.waitForTimeout(200)
  }
  throw Error('Map state transition timed out')
}
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
    globalThis.__atlasPaint = { labels: [], connections: 0, circles: [] }
    const originalText = CanvasRenderingContext2D.prototype.fillText
    const originalStroke = CanvasRenderingContext2D.prototype.stroke
    const originalClear = CanvasRenderingContext2D.prototype.clearRect
    const originalArc = CanvasRenderingContext2D.prototype.arc
    CanvasRenderingContext2D.prototype.arc = function (...args) {
      globalThis.__atlasPaint.circles.push({ x: args[0], y: args[1] })
      return originalArc.apply(this, args)
    }
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      globalThis.__atlasPaint = { labels: [], connections: 0, circles: [] }
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
  async function readAvailable() {
    const deadline = Date.now() + 60000
    let value
    while (Date.now() < deadline) {
      value = await page.evaluate(() => window.desktop.readMap())
      if (value.available) return value
      await page.waitForTimeout(300)
    }
    throw Error(`Live atlas unavailable: ${value?.reason}`)
  }
  let snapshot = await readAvailable()
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
  await overlay.evaluate(() =>
    window.atlasOverlay.onFrame((frame) => {
      globalThis.__lastAtlasFrame = frame
    })
  )
  await overlay.waitForFunction(() => globalThis.__atlasPaint.circles.length > 0, null, {
    timeout: 10000
  })
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
  const readStyle = () => {
    const check = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        `Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class PickStyleCheck { [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtrW(IntPtr h,int i); }'; [PickStyleCheck]::GetWindowLongPtrW([IntPtr]${evidence.window.handle}, -20).ToInt64()`
      ],
      { encoding: 'utf8', windowsHide: true }
    )
    assert.equal(check.status, 0, check.stderr)
    return Number(check.stdout.trim())
  }
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
  await page.evaluate(() =>
    window.desktop.setMapOverlay({
      pathWidth: 5,
      pathColor: '#12abcd',
      opacity: 10,
      allowBackground: true
    })
  )
  const changedOptions = (await page.evaluate(() => window.desktop.getMapStatus())).overlay
  assert.equal(changedOptions.pathWidth, 5)
  assert.equal(changedOptions.pathColor, '#12abcd')
  assert.equal(changedOptions.opacity, 10)
  await page.evaluate(() =>
    window.desktop.setMapOverlay({
      pathWidth: 3,
      pathColor: '#74ffd0',
      opacity: 85,
      allowBackground: false
    })
  )
  await page.evaluate(() => window.desktop.setMapPicking(true))
  assert.equal(readStyle() & 0x20, 0, 'picking temporarily receives mouse')
  await overlay.waitForTimeout(250)
  const pick = await overlay.evaluate(() =>
    globalThis.__atlasPaint.circles.find(
      (n) =>
        n.x > innerWidth * 0.3 && n.x < innerWidth * 0.7 && n.y > 220 && n.y < innerHeight * 0.65
    )
  )
  assert.ok(pick, 'actually painted live node to select')
  assert.equal(
    await overlay.locator('canvas').evaluate((c) => getComputedStyle(c).pointerEvents),
    'auto'
  )
  await overlay.mouse.click(pick.x, pick.y)
  await waitState(page, (state) => state.planning.mode === 'manual', 5000)
  const pickedState = (await page.evaluate(() => window.desktop.getMapStatus())).planning
  assert.equal(pickedState.mode, 'manual')
  assert.ok(
    snapshot.nodes.some(
      (n) => n.grid.x === pickedState.start?.x && n.grid.y === pickedState.start?.y
    )
  )
  assert.ok((readStyle() & 0x20) !== 0, 'selection restores mouse passthrough')
  evidence.pickedStart = pickedState.start
  const rejectedSender = await application.evaluate(async ({ BrowserWindow, app }) => {
    const other = new BrowserWindow({
      show: false,
      webPreferences: {
        preload: app.getAppPath() + '/out/preload/overlay.cjs',
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false
      }
    })
    try {
      await other.loadURL('about:blank')
      return await other.webContents.executeJavaScript(
        "window.atlasOverlay.pick(null).then(() => '', e => String(e))"
      )
    } finally {
      other.destroy()
    }
  })
  assert.match(rejectedSender, /无效覆盖层来源/)
  await assert.rejects(overlay.evaluate(() => window.atlasOverlay.pick('0,0')))
  await page.evaluate(() => window.desktop.setMapPicking(true))
  await overlay.waitForTimeout(200)
  await overlay.mouse.click(pick.x, pick.y, { button: 'right' })
  await waitState(page, (state) => !state.picking)
  assert.ok((readStyle() & 0x20) !== 0, 'right click restores mouse passthrough')
  await page.evaluate(() => window.desktop.setMapPicking(true))
  const timeoutStart = Date.now()
  await waitState(page, (state) => !state.picking, 25000)
  evidence.pickTimeoutMs = Date.now() - timeoutStart
  assert.ok(
    evidence.pickTimeoutMs <= 22000,
    'picking ends within 20 seconds or earlier on invalid frame'
  )
  assert.ok((readStyle() & 0x20) !== 0, 'timeout restores mouse passthrough')
  evidence.checks.push(
    '真实节点经覆盖层点击选为起点；选择完成、右键取消及失效帧/超时结束均恢复原生鼠标穿透；非选择状态的伪造请求被拒绝'
  )
  if (candidate) {
    await page.evaluate(
      (target) => window.desktop.planMapRoute({ mode: 'current', target }),
      candidate.b
    )
    await page
      .getByRole('button', { name: '应用设置', exact: true })
      .evaluate((button) => button.click())
    const persistedRoute = await page.evaluate(() => window.desktop.readMap())
    assert.ok(persistedRoute.route)
    assert.equal(persistedRoute.route.includePlayerGuide, true)
    assert.ok(
      persistedRoute.player && Number.isFinite(persistedRoute.player.x + persistedRoute.player.y)
    )
    evidence.checks.push('切页后主进程仍返回同帧路线与人物像素位置，普通路线保留人物引导标志')
  }
  const resetting = await page.evaluate(() => window.desktop.readMap(true))
  assert.equal(resetting.available, false)
  await readAvailable()
  evidence.checks.push('实机重新校准立即隐藏旧图，等待连续有效帧后恢复')
  await page.evaluate(() => window.desktop.setMapOverlay({ allowBackground: true }))
  await application.evaluate(({ BrowserWindow }) => {
    const main = BrowserWindow.getAllWindows().find((w) => w.getTitle() === 'POE 物价补丁')
    main.setPosition(-20000, -20000)
    main.restore()
    main.show()
    main.focus()
  })
  await page.waitForTimeout(800)
  const backgroundFrame = await page.evaluate(() => window.desktop.readMap())
  assert.equal(backgroundFrame.gameWindow.foreground, false)
  assert.equal(
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()
        .find((w) => w.getTitle() === 'POE2 世界地图覆盖层')
        .isVisible()
    ),
    true
  )
  await page.evaluate(() => window.desktop.setMapOverlay({ allowBackground: false }))
  assert.equal(
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()
        .find((w) => w.getTitle() === 'POE2 世界地图覆盖层')
        .isVisible()
    ),
    false
  )
  const refocus = spawnSync(
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
  assert.equal(refocus.status, 0, refocus.stderr)
  await readAvailable()
  evidence.checks.push('非覆盖层窗口的选择请求被拒绝；后台显示开关实际控制失焦后的可见性')
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
} catch (error) {
  evidence.failure = String(error)
  evidence.diagnostic = await application
    .firstWindow()
    .then((p) =>
      p.evaluate(async () => {
        const state = await window.desktop.getMapStatus()
        const sample = state.enabled ? await window.desktop.readMap() : null
        return {
          state,
          sample: sample && {
            available: sample.available,
            reason: sample.reason,
            nodes: sample.nodes.length,
            game: sample.gameWindow
          }
        }
      })
    )
    .catch((e) => String(e))
  const surface = application.windows().find((p) => p.url().includes('overlay.html'))
  if (surface)
    evidence.overlayDiagnostic = await surface
      .evaluate(() => {
        const frame = globalThis.__lastAtlasFrame,
          nodes = frame?.snapshot.nodes || []
        return {
          painted: globalThis.__atlasPaint,
          snapshot: frame && {
            available: frame.snapshot.available,
            game: frame.snapshot.gameWindow,
            picking: frame.picking
          },
          width: innerWidth,
          height: innerHeight,
          inView: nodes.filter(
            (n) => n.x > 64 && n.x < innerWidth - 76 && n.y > 105 && n.y < innerHeight - 100
          ).length,
          firstNode: nodes[0],
          lastNode: nodes.at(-1)
        }
      })
      .catch((e) => String(e))
  console.error(
    JSON.stringify({
      failure: evidence.failure,
      diagnostic: evidence.diagnostic,
      overlayDiagnostic: evidence.overlayDiagnostic && {
        ...evidence.overlayDiagnostic,
        painted: {
          labels: evidence.overlayDiagnostic.painted?.labels?.length,
          circles: evidence.overlayDiagnostic.painted?.circles?.length
        }
      }
    })
  )
  throw error
} finally {
  await fs.writeFile(
    path.join(report, `world-map-overlay${packaged ? '-packaged' : ''}.json`),
    JSON.stringify(evidence, null, 2)
  )
  await application.close()
}
