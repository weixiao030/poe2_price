import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { EventEmitter } from 'node:events'
import ts from 'typescript'
import { overlayDefaults } from '../src/shared/world-map'

test('overlay selection is scoped to its frame, cancels at 20 seconds and restores passthrough on stale data', () => {
  const handlers = new Map<string, Function>()
  const timeouts: { callback: Function; delay: number; cancelled: boolean }[] = []
  const intervals: Function[] = []
  let now = 1000
  class Window extends EventEmitter {
    static latest: Window
    webContents = Object.assign(new EventEmitter(), {
      mainFrame: {},
      send: () => {},
      setWindowOpenHandler: () => {}
    })
    ignore = true
    visible = false
    constructor() {
      super()
      Window.latest = this
    }
    setIgnoreMouseEvents(value: boolean) {
      this.ignore = value
    }
    setAlwaysOnTop() {}
    setBounds() {}
    isDestroyed() {
      return false
    }
    hide() {
      this.visible = false
    }
    showInactive() {
      this.visible = true
    }
    isVisible() {
      return this.visible
    }
    loadFile() {
      this.webContents.emit('did-finish-load')
      return Promise.resolve()
    }
    destroy() {
      this.emit('closed')
    }
  }
  const source = fs
    .readFileSync(new URL('../src/main/world-map-overlay.ts', import.meta.url), 'utf8')
    .replaceAll('import.meta.url', JSON.stringify(import.meta.url))
  const context = vm.createContext({
    exports: {},
    process: { env: {} },
    Date: { now: () => now },
    require: (id: string) =>
      id === 'electron'
        ? {
            app: { isPackaged: true },
            BrowserWindow: Window,
            screen: { screenToDipRect: (_: unknown, r: unknown) => r },
            ipcMain: { handle: (name: string, callback: Function) => handlers.set(name, callback) }
          }
        : id === 'node:path'
          ? path
          : id === 'node:url'
            ? { fileURLToPath: () => '/fixture/main.js' }
            : { gridId: (p: { x: number; y: number }) => `${p.x},${p.y}` },
    setTimeout: (callback: Function, delay: number) => {
      const timer = { callback, delay, cancelled: false }
      timeouts.push(timer)
      return timer
    },
    clearTimeout: (timer: { cancelled: boolean } | undefined) => {
      if (timer) timer.cancelled = true
    },
    setInterval: (callback: Function) => {
      intervals.push(callback)
      return { unref() {} }
    },
    clearInterval() {}
  })
  vm.runInContext(
    ts.transpile(source, { module: ts.ModuleKind.CommonJS, esModuleInterop: true }),
    context
  )
  const overlay = new context.exports.WorldMapOverlay()
  const snapshot = {
    available: true,
    nodes: [{ id: '1,2', grid: { x: 1, y: 2 } }],
    edges: [],
    gameWindow: { foreground: true, left: 0, top: 0, width: 1000, height: 800 }
  }
  overlay.update(snapshot, overlayDefaults)
  const own = {
    sender: Window.latest.webContents,
    senderFrame: Window.latest.webContents.mainFrame
  }
  const handler = handlers.get('map:overlay-pick')!
  assert.equal(Window.latest.ignore, true)
  assert.throws(() => handler(own, '1,2'), /选择状态/)
  overlay.setPicking(true)
  assert.equal(Window.latest.ignore, false)
  assert.throws(() => handler({ ...own, senderFrame: {} }, null), /无效覆盖层来源/)
  assert.throws(() => handler(own, '99,99'), /节点已离开/)
  assert.equal(timeouts.at(-1)?.delay, 20000)
  timeouts.at(-1)!.callback()
  assert.equal(overlay.picking, false)
  assert.equal(Window.latest.ignore, true)
  overlay.setPicking(true)
  let selected: unknown
  overlay.onSelected = (point: unknown) => {
    selected = point
  }
  handler(own, '1,2')
  assert.deepEqual(selected, { x: 1, y: 2 })
  assert.equal(Window.latest.ignore, true)
  overlay.setPicking(true)
  now += 1001
  intervals[0]()
  assert.equal(overlay.picking, false)
  assert.equal(Window.latest.ignore, true)
  assert.equal(Window.latest.visible, false)
})
