import type { AtlasNode, GridPoint } from './world-map'
export function safeAtlasSegment(
  a: { x: number; y: number },
  b: { x: number; y: number },
  width: number,
  height: number
) {
  return (
    [a.x, a.y, b.x, b.y].every(Number.isFinite) &&
    Math.hypot(a.x - b.x, a.y - b.y) <= Math.max(160, Math.min(width, height) * 0.22)
  )
}
export function safeAtlasEdge(a: GridPoint, b: GridPoint) {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) <= 16
}
export function rankAtlasNodes(nodes: AtlasNode[], origin: GridPoint | null) {
  return nodes
    .map((node) => ({
      ...node,
      distance: origin ? Math.hypot(node.grid.x - origin.x, node.grid.y - origin.y) : null,
      delta: origin
        ? `X${signed(node.grid.x - origin.x)} · Y${signed(node.grid.y - origin.y)}`
        : '距离基准尚未确认'
    }))
    .sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity) || a.number - b.number)
}
const signed = (value: number) => (value >= 0 ? `+${value}` : String(value))
