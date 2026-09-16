export interface GridPoint {
  x: number
  y: number
}
export interface AtlasNode {
  id: string
  number: number
  grid: GridPoint
  x: number
  y: number
  name: string
  displayName: string
  areaId: string
  isHidden: boolean
  state: number
  stateText: string
  canOpen: boolean
  contentTags: string[]
  contentLabels: string[]
}
export interface AtlasSnapshot {
  available: boolean
  reason: string
  nodes: AtlasNode[]
  edges: { a: GridPoint; b: GridPoint }[]
  currentNode: GridPoint | null
  readMilliseconds: number
  capturedAt: string
  unknownNameCount: number
  gameWindow: {
    left: number
    top: number
    width: number
    height: number
    foreground: boolean
  } | null
}
export interface AtlasRoute {
  found: boolean
  path: GridPoint[]
  distance: number
  message: string
  includePlayerGuide: boolean
}
export interface OverlayOptions {
  visible: boolean
  numbers: boolean
  names: boolean
  hidden: boolean
  connections: boolean
  opacity: number
}
export const overlayDefaults: OverlayOptions = {
  visible: true,
  numbers: true,
  names: true,
  hidden: true,
  connections: true,
  opacity: 85
}
export interface MapPreferences {
  directory: string
  consentVersion: number
  enabled?: boolean
  overlay?: OverlayOptions
}
export const MAP_RISK =
  '本功能需要读取游戏内存，会有封号风险，使用者自行承担全部风险。仅限 POE2 国际服使用，国服及其他服不能使用，也禁止使用。不写入游戏内存、不修改游戏文件。'
export interface MapStatus {
  enabled: boolean
  authorized: boolean
  directory: string
  overlay: OverlayOptions
  consentToken?: string
}
export interface OverlayFrame {
  snapshot: AtlasSnapshot
  route: AtlasRoute | null
  options: OverlayOptions
}
export interface RouteRequest {
  mode: 'accessible' | 'current' | 'manual'
  target: GridPoint
  start?: GridPoint
}
export const gridId = (point: GridPoint) => `${point.x},${point.y}`
