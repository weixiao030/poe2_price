import type { OverlayFrame, AtlasNode } from '../shared/world-map'
import { gridId } from '../shared/world-map'
import { safeAtlasSegment, safeAtlasEdge } from '../shared/atlas-geometry'
import './overlay.css'
declare global {
  interface Window {
    atlasOverlay: {
      onFrame(callback: (frame: OverlayFrame) => void): () => void
      pick(id: string | null): Promise<void>
    }
  }
}
const canvas = document.getElementById('atlas') as HTMLCanvasElement
let latest: OverlayFrame | null = null,
  scheduled = 0,
  lastFrame = 0
let hitBoxes: { id: string; x: number; y: number; w: number; h: number }[] = []
function paint() {
  scheduled = 0
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1,
    width = innerWidth,
    height = innerHeight
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)
  hitBoxes = []
  canvas.style.cursor = latest?.picking ? 'crosshair' : 'default'
  canvas.style.pointerEvents = latest?.picking ? 'auto' : 'none'
  if (
    !latest?.snapshot.available ||
    (!latest.snapshot.gameWindow?.foreground && !latest.options.allowBackground) ||
    Date.now() - lastFrame > 1000
  )
    return
  const { snapshot, options, route } = latest
  const game = snapshot.gameWindow!
  const sx = width / game.width,
    sy = height / game.height
  const point = (n: AtlasNode) => ({ x: n.x * sx, y: n.y * sy })
  const nodes = new Map(snapshot.nodes.map((n) => [n.id, n]))
  const routeIds = new Set(route?.found ? route.path.map(gridId) : [])
  const currentId = snapshot.currentNode ? gridId(snapshot.currentNode) : ''
  const inMap = (p: { x: number; y: number }) =>
    Number.isFinite(p.x + p.y) &&
    p.x >= 64 &&
    p.x <= width - 76 &&
    p.y >= 105 &&
    p.y <= height - 100 &&
    !(p.y > height * 0.72 && (p.x < width * 0.19 || p.x > width * 0.8))
  const safeLine = (a: AtlasNode, b: AtlasNode) => {
    const p = point(a),
      q = point(b)
    return safeAtlasSegment(p, q, width, height) && safeAtlasEdge(a.grid, b.grid)
  }
  // Keep connections and labels out of the game's navigation and combat HUD.
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(64, 105)
  ctx.lineTo(width - 76, 105)
  ctx.lineTo(width - 76, height * 0.72)
  ctx.lineTo(width * 0.8, height * 0.72)
  ctx.lineTo(width * 0.8, height - 100)
  ctx.lineTo(width * 0.19, height - 100)
  ctx.lineTo(width * 0.19, height * 0.72)
  ctx.lineTo(64, height * 0.72)
  ctx.closePath()
  ctx.clip()
  ctx.globalAlpha = options.opacity / 100
  if (options.connections) {
    ctx.beginPath()
    for (const e of snapshot.edges) {
      const a = nodes.get(gridId(e.a)),
        b = nodes.get(gridId(e.b))
      if (!a || !b || !safeLine(a, b) || (!options.hidden && (a.isHidden || b.isHidden))) continue
      const p = point(a),
        q = point(b)
      ctx.moveTo(p.x, p.y)
      ctx.lineTo(q.x, q.y)
    }
    ctx.strokeStyle = '#081a21b0'
    ctx.lineWidth = 4
    ctx.stroke()
    ctx.strokeStyle = '#8de2f5c0'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }
  if (route?.found) {
    const first = route.path.length ? nodes.get(gridId(route.path[0])) : null
    if (route.includePlayerGuide && snapshot.player && first) {
      const p = { x: snapshot.player.x * sx, y: snapshot.player.y * sy },
        q = point(first)
      if (safeAtlasSegment(p, q, width, height)) {
        ctx.beginPath()
        ctx.moveTo(p.x, p.y)
        ctx.lineTo(q.x, q.y)
        ctx.strokeStyle = options.pathColor
        ctx.lineWidth = options.pathWidth
        ctx.stroke()
      }
    }
    for (let i = 1; i < route.path.length; i++) {
      const a = nodes.get(gridId(route.path[i - 1])),
        b = nodes.get(gridId(route.path[i]))
      if (!a || !b || !safeLine(a, b)) continue
      const p = point(a),
        q = point(b)
      ctx.beginPath()
      ctx.moveTo(p.x, p.y)
      ctx.lineTo(q.x, q.y)
      ctx.strokeStyle = '#07140fed'
      ctx.lineWidth = options.pathWidth + 4
      ctx.stroke()
      ctx.strokeStyle = options.pathColor
      ctx.lineWidth = options.pathWidth
      ctx.stroke()
      const angle = Math.atan2(q.y - p.y, q.x - p.x),
        mx = (p.x + q.x) / 2,
        my = (p.y + q.y) / 2
      ctx.fillStyle = '#b4ffe4'
      ctx.beginPath()
      ctx.moveTo(mx + Math.cos(angle) * 7, my + Math.sin(angle) * 7)
      ctx.lineTo(mx + Math.cos(angle + 2.5) * 7, my + Math.sin(angle + 2.5) * 7)
      ctx.lineTo(mx + Math.cos(angle - 2.5) * 7, my + Math.sin(angle - 2.5) * 7)
      ctx.closePath()
      ctx.fill()
    }
  }
  const boxes: { x: number; y: number; w: number; h: number }[] = []
  const ordered = [...snapshot.nodes].sort(
    (a, b) =>
      Number(routeIds.has(b.id) || b.id === currentId) -
      Number(routeIds.has(a.id) || a.id === currentId)
  )
  for (const n of ordered) {
    if (n.isHidden && !options.hidden) continue
    const p = point(n)
    if (!inMap(p)) continue
    hitBoxes.push({ id: n.id, x: p.x - 10, y: p.y - 10, w: 20, h: 20 })
    const current = n.id === currentId,
      inRoute = routeIds.has(n.id)
    const color = current
      ? '#ff9b88'
      : inRoute
        ? '#74ffd0'
        : n.canOpen
          ? '#9df2be'
          : n.isHidden
            ? '#90ddff'
            : n.state === 0
              ? '#b5bfcb'
              : '#ffdb8c'
    ctx.beginPath()
    ctx.arc(p.x, p.y, current ? 10 : 6, 0, Math.PI * 2)
    ctx.strokeStyle = '#071410eb'
    ctx.lineWidth = 4
    ctx.stroke()
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.stroke()
    let text = [
      current ? '当前位置' : '',
      options.numbers ? String(n.number) : '',
      options.names || inRoute ? n.displayName : ''
    ]
      .filter(Boolean)
      .join(' ')
    if (!text) continue
    ctx.font = '13px "Segoe UI", "Microsoft YaHei UI", sans-serif'
    if (ctx.measureText(text).width > 200) {
      while (text.length && ctx.measureText(text + '…').width > 200) text = text.slice(0, -1)
      text += '…'
    }
    const w = ctx.measureText(text).width + 12,
      h = 23
    const candidates = [
      { x: p.x - w / 2, y: p.y + 10, w, h },
      { x: p.x - w / 2, y: p.y - h - 10, w, h },
      { x: p.x + 12, y: p.y - h / 2, w, h },
      { x: p.x - w - 12, y: p.y - h / 2, w, h }
    ]
    const box = candidates.find(
      (box) =>
        inMap(box) &&
        inMap({ x: box.x + w, y: box.y + h }) &&
        !boxes.some(
          (b) =>
            box.x < b.x + b.w + 3 &&
            box.x + box.w + 3 > b.x &&
            box.y < b.y + b.h + 3 &&
            box.y + box.h + 3 > b.y
        )
    )
    if (!box) continue
    boxes.push(box)
    hitBoxes.push({ id: n.id, ...box })
    ctx.fillStyle = '#0b131bed'
    ctx.fillRect(box.x, box.y, box.w, box.h)
    ctx.strokeStyle = color + '80'
    ctx.lineWidth = 1
    ctx.strokeRect(box.x, box.y, box.w, box.h)
    ctx.save()
    ctx.beginPath()
    ctx.rect(box.x + 3, box.y, w - 6, h)
    ctx.clip()
    ctx.fillStyle = color
    ctx.fillText(text, box.x + 6, box.y + 16)
    ctx.restore()
  }
  ctx.restore()
  if (latest.picking) {
    ctx.fillStyle = '#111d2af2'
    ctx.fillRect(width / 2 - 195, 58, 390, 34)
    ctx.font = '14px "Microsoft YaHei UI", sans-serif'
    ctx.fillStyle = '#e8f4ff'
    ctx.textAlign = 'center'
    ctx.fillText('点击节点设为起点 · 右键取消 · 20 秒后退出', width / 2, 80)
    ctx.textAlign = 'start'
  }
}
canvas.addEventListener('pointerdown', (event) => {
  if (!latest?.picking || !latest.snapshot.gameWindow?.foreground || Date.now() - lastFrame > 1000)
    return
  event.preventDefault()
  if (event.button === 2) {
    void window.atlasOverlay.pick(null).catch(() => {})
    return
  }
  if (event.button !== 0) return
  const hit = hitBoxes
    .slice()
    .reverse()
    .find(
      (box) =>
        event.clientX >= box.x &&
        event.clientX <= box.x + box.w &&
        event.clientY >= box.y &&
        event.clientY <= box.y + box.h
    )
  if (hit) void window.atlasOverlay.pick(hit.id).catch(() => {})
})
canvas.addEventListener('contextmenu', (event) => event.preventDefault())
function schedule() {
  if (!scheduled) scheduled = requestAnimationFrame(paint)
}
window.atlasOverlay.onFrame((frame) => {
  latest = frame
  lastFrame = Date.now()
  schedule()
})
window.addEventListener('resize', schedule)
setInterval(() => {
  if (Date.now() - lastFrame > 1000) schedule()
}, 250)
