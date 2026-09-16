import { app, BrowserWindow, screen, ipcMain } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type {
  AtlasRoute,
  AtlasSnapshot,
  OverlayFrame,
  OverlayOptions,
  GridPoint
} from '../shared/world-map'
import { gridId } from '../shared/world-map'

export class WorldMapOverlay {
  private window: BrowserWindow | null = null
  private ready = false
  private route: AtlasRoute | null = null
  private lastFrame: OverlayFrame | null = null
  private watchdog: NodeJS.Timeout | undefined
  private lastUpdate = 0
  private bounds = ''
  private pickTimer: NodeJS.Timeout | undefined
  private interactive = false
  onSelected?: (point: GridPoint) => void
  onPickingChanged?: () => void
  get picking() {
    return this.interactive
  }
  constructor() {
    ipcMain.handle('map:overlay-pick', (event, id: unknown) => {
      if (
        !this.window ||
        event.sender !== this.window.webContents ||
        event.senderFrame !== this.window.webContents.mainFrame
      )
        throw new Error('无效覆盖层来源')
      if (!this.interactive) throw new Error('当前未处于起点选择状态')
      if (id === null) {
        this.setPicking(false)
        return
      }
      if (
        typeof id !== 'string' ||
        id.length > 40 ||
        !this.lastFrame?.snapshot.available ||
        !this.lastFrame.snapshot.gameWindow?.foreground ||
        Date.now() - this.lastUpdate > 1000
      )
        throw new Error('地图状态已变化，请重新选择')
      const node = this.lastFrame.snapshot.nodes.find((n) => n.id === id)
      if (!node) throw new Error('节点已离开当前地图')
      this.setPicking(false)
      this.onSelected?.(node.grid)
    })
  }
  setPicking(enabled: boolean) {
    if (enabled && (!this.lastFrame?.snapshot.available || !this.lastFrame.options.visible))
      throw new Error('请先开启游戏覆盖层并打开世界地图')
    clearTimeout(this.pickTimer)
    this.interactive = enabled
    this.window?.setIgnoreMouseEvents(!enabled, { forward: true })
    if (this.lastFrame) {
      this.lastFrame = { ...this.lastFrame, picking: enabled }
      if (this.ready) this.window?.webContents.send('map:overlay-frame', this.lastFrame)
    }
    if (enabled) this.pickTimer = setTimeout(() => this.setPicking(false), 20_000)
    this.onPickingChanged?.()
  }
  hide() {
    this.window?.hide()
    if (this.interactive) this.setPicking(false)
    this.route = null
    this.lastFrame = null
  }
  setRoute(route: AtlasRoute | null) {
    this.route = route
  }

  update(snapshot: AtlasSnapshot, options: OverlayOptions) {
    this.lastUpdate = Date.now()
    const game = snapshot.gameWindow
    this.lastFrame = { snapshot, route: this.route, options, picking: this.interactive }
    if ((!snapshot.available || !options.visible) && this.interactive) this.setPicking(false)
    if (
      !options.visible ||
      !snapshot.available ||
      !game ||
      (!game.foreground && !options.allowBackground) ||
      ![game.left, game.top, game.width, game.height].every(Number.isFinite) ||
      game.width < 100 ||
      game.height < 100
    ) {
      this.window?.hide()
      if (!snapshot.available) this.route = null
      return
    }
    if (this.route) {
      const nodes = new Map(snapshot.nodes.map((n) => [n.id, n]))
      const edges = new Set(
        snapshot.edges.flatMap((e) => [
          `${gridId(e.a)}|${gridId(e.b)}`,
          `${gridId(e.b)}|${gridId(e.a)}`
        ])
      )
      const steps = this.route.path.map(gridId)
      if (
        steps.some((id) => !nodes.has(id)) ||
        steps.slice(1).some((id, i) => !edges.has(`${steps[i]}|${id}`)) ||
        (!this.route.includePlayerGuide && steps.length && !nodes.get(steps[0])?.canOpen)
      )
        this.route = null
    }
    if (!this.window || this.window.isDestroyed()) this.create()
    const window = this.window!
    const rectangle = screen.screenToDipRect(null, {
      x: game.left,
      y: game.top,
      width: game.width,
      height: game.height
    })
    const key = JSON.stringify(rectangle)
    if (this.bounds !== key) {
      window.setBounds(rectangle)
      this.bounds = key
    }
    this.lastFrame = { snapshot, route: this.route, options, picking: this.interactive }
    window.setIgnoreMouseEvents(!this.interactive || !game.foreground, { forward: true })
    if (this.ready) {
      window.webContents.send('map:overlay-frame', this.lastFrame)
      if (!window.isVisible()) window.showInactive()
    }
  }

  private create() {
    const here = path.dirname(fileURLToPath(import.meta.url))
    const window = new BrowserWindow({
      width: 800,
      height: 600,
      transparent: true,
      frame: false,
      hasShadow: false,
      show: false,
      focusable: false,
      skipTaskbar: true,
      resizable: false,
      title: 'POE2 世界地图覆盖层',
      backgroundColor: '#00000000',
      webPreferences: {
        preload: path.join(here, '../preload/overlay.cjs'),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        backgroundThrottling: false
      }
    })
    this.window = window
    window.setIgnoreMouseEvents(true, { forward: true })
    window.setAlwaysOnTop(true, 'screen-saver')
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    window.webContents.on('will-navigate', (event) => event.preventDefault())
    window.webContents.once('did-finish-load', () => {
      if (this.window === window) this.ready = true
    })
    window.on('closed', () => {
      if (this.window === window) {
        this.window = null
        this.ready = false
      }
    })
    if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL)
      void window.loadURL(new URL('overlay.html', process.env.ELECTRON_RENDERER_URL).href)
    else void window.loadFile(path.join(here, '../renderer/overlay.html'))
    clearInterval(this.watchdog)
    this.watchdog = setInterval(() => {
      if (Date.now() - this.lastUpdate > 1000) this.hide()
    }, 250)
    this.watchdog.unref()
  }

  stop() {
    this.setPicking(false)
    clearInterval(this.watchdog)
    this.window?.destroy()
    this.window = null
    this.ready = false
    this.route = null
    this.lastFrame = null
    this.bounds = ''
  }
}
