import { _electron as electron } from 'playwright'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'poe-overlay-render-'))
const env = { ...process.env, POE_DESKTOP_DATA: profile }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ args: [root, '--hidden'], env })
const checks = []
try {
  await app.firstWindow()
  await app.evaluate(async ({ BrowserWindow, app }) => {
    const surface = new BrowserWindow({
      show: false,
      width: 900,
      height: 600,
      frame: false,
      webPreferences: {
        preload: app.getAppPath() + '/out/preload/overlay.cjs',
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        backgroundThrottling: false
      }
    })
    await surface.loadFile(app.getAppPath() + '/out/renderer/overlay.html')
  })
  const page = app.windows().find((p) => p.url().includes('overlay.html'))
  assert.ok(page)
  const node = {
    id: '0,0',
    grid: { x: 0, y: 0 },
    x: 300,
    y: 250,
    number: 1,
    displayName: '测试节点',
    name: 'fixture',
    state: 1,
    canOpen: true,
    isHidden: false
  }
  const frame = {
    snapshot: {
      available: true,
      gameWindow: { width: 900, height: 600, foreground: true },
      nodes: [node],
      edges: [],
      currentNode: null,
      player: { x: 250, y: 250 }
    },
    route: { found: true, path: [node.grid], includePlayerGuide: true },
    options: {
      visible: true,
      opacity: 100,
      pathWidth: 5,
      pathColor: '#ff0000',
      connections: true,
      names: true,
      numbers: true,
      hidden: true,
      allowBackground: false
    },
    picking: false
  }
  const send = async () => {
    await app.evaluate(({ BrowserWindow }, value) => {
      const surface = BrowserWindow.getAllWindows().find((w) =>
        w.webContents.getURL().includes('overlay.html')
      )
      globalThis.__overlayFixture = value
      if (!globalThis.__overlayFixtureTimer) {
        globalThis.__overlayFixtureTimer = setInterval(
          () => surface.webContents.send('map:overlay-frame', globalThis.__overlayFixture),
          80
        )
        surface.on('closed', () => clearInterval(globalThis.__overlayFixtureTimer))
      }
      surface.webContents.send('map:overlay-frame', value)
    }, frame)
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    )
  }
  const pixel = (x, y) =>
    page
      .locator('canvas')
      .evaluate(
        (canvas, [x, y]) =>
          Array.from(
            canvas
              .getContext('2d')
              .getImageData(
                Math.round(x * devicePixelRatio),
                Math.round(y * devicePixelRatio),
                1,
                1
              ).data
          ),
        [x, y]
      )
  await send()
  assert.deepEqual(await pixel(275, 250), [255, 0, 0, 255])
  checks.push('ordinary route draws player-to-start guide with configured color')
  frame.route.includePlayerGuide = false
  await send()
  assert.equal((await pixel(275, 250))[3], 0)
  checks.push('optimal accessible route omits player guide')
  frame.snapshot.nodes.push({ ...node, id: '1,0', grid: { x: 1, y: 0 }, x: 400, number: 2 })
  frame.snapshot.edges = [{ a: node.grid, b: frame.snapshot.nodes[1].grid }]
  frame.route.path.push(frame.snapshot.nodes[1].grid)
  await send()
  assert.ok((await pixel(325, 250))[3] > 0)
  assert.ok((await pixel(325, 252))[3] > 0)
  frame.options.pathWidth = 1
  await send()
  assert.notDeepEqual(await pixel(325, 252), [255, 0, 0, 255])
  checks.push('valid connections, route and width changes actually render')
  frame.snapshot.nodes[1].x = 750
  frame.snapshot.edges[0].b = { x: 17, y: 0 }
  frame.snapshot.nodes[1].grid = { x: 17, y: 0 }
  frame.snapshot.nodes[1].id = '17,0'
  frame.route.path = [node.grid, { x: 17, y: 0 }]
  await send()
  assert.equal((await pixel(500, 250))[3], 0)
  checks.push('torn-frame long edge and route are not painted')
  frame.snapshot.gameWindow.foreground = false
  await send()
  assert.equal((await pixel(300, 244))[3], 0)
  frame.options.allowBackground = true
  await send()
  assert.ok((await pixel(300, 244))[3] > 0)
  checks.push('background display option controls actual canvas painting')
  await fs.mkdir(path.join(root, 'test-results'), { recursive: true })
  await fs.writeFile(
    path.join(root, 'test-results/overlay-renderer.json'),
    JSON.stringify({ scope: 'production renderer with explicit offline fixtures', checks }, null, 2)
  )
  console.log(JSON.stringify({ checks }, null, 2))
} finally {
  await app.close()
}
