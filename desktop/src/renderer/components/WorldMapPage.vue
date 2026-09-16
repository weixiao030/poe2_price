<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import {
  NAlert,
  NButton,
  NCheckbox,
  NInput,
  NModal,
  NPagination,
  NSelect,
  NSlider,
  NSwitch,
  NTag,
  useMessage
} from 'naive-ui'
import { useAppStore } from '../stores/app'
import type {
  AtlasNode,
  AtlasRoute,
  AtlasSnapshot,
  MapStatus,
  RouteRequest,
  OverlayOptions
} from '../../shared/world-map'
import { gridId, overlayDefaults, planningDefaults, MAP_RISK } from '../../shared/world-map'
import { rankAtlasNodes } from '../../shared/atlas-geometry'
import '../world-map.css'
const api = window.desktop,
  app = useAppStore(),
  message = useMessage()
const status = ref<MapStatus>({
  enabled: false,
  authorized: false,
  directory: '',
  overlay: { ...overlayDefaults },
  planning: { ...planningDefaults },
  picking: false
})
const map = shallowRef<AtlasSnapshot | null>(null),
  route = shallowRef<AtlasRoute | null>(null)
const selected = ref<string | null>(null),
  startId = ref<string | null>(null)
const mode = ref<RouteRequest['mode']>('accessible'),
  query = ref(''),
  results = shallowRef<string[]>([])
const hidden = ref(true),
  labels = ref(false),
  busy = ref(false),
  error = ref('')
const consentVisible = ref(false),
  consentAcknowledged = ref(false),
  consentToken = ref('')
const cancelConsentButton = ref<InstanceType<typeof NButton>>()
const canvas = ref<HTMLCanvasElement>(),
  host = ref<HTMLDivElement>()
const zoom = ref(1)
const allNodes = computed(() => map.value?.nodes || [])
const nodes = computed(() => allNodes.value.filter((n) => hidden.value || !n.isHidden))
const selectedNode = computed(() => allNodes.value.find((n) => n.id === selected.value))
const searchNodes = computed(() => {
  const matching = new Set(results.value)
  return rankAtlasNodes(
    query.value.trim()
      ? allNodes.value.filter((n) => matching.has(n.id))
      : allNodes.value.filter((n) => n.canOpen),
    mode.value === 'manual' ? parseGrid(startId.value) : (map.value?.currentNode ?? null)
  )
})
const resultPage = ref(1)
const pageNodes = computed(() =>
  searchNodes.value.slice((resultPage.value - 1) * 60, resultPage.value * 60)
)
const pageCount = computed(() => Math.max(1, Math.ceil(searchNodes.value.length / 60)))
watch(pageCount, (count) => {
  if (resultPage.value > count) resultPage.value = count
})
function parseGrid(value: string | null) {
  if (!value) return null
  const [x, y] = value.split(',').map(Number)
  return { x, y }
}
const nodeIndex = computed(() => new Map(allNodes.value.map((n) => [n.id, n])))
let timer: ReturnType<typeof setTimeout> | undefined,
  debounce: ReturnType<typeof setTimeout> | undefined
let observer: ResizeObserver | undefined,
  disposed = false,
  queryGeneration = 0
let restoring = true
const unsubscribe: (() => void)[] = []
async function persistPlanning() {
  if (restoring || disposed) return
  try {
    const updated = await api.setMapPlanning({
      query: query.value,
      selected: parseGrid(selected.value),
      start: parseGrid(startId.value),
      mode: mode.value
    })
    status.value = updated
  } catch (e) {
    error.value = (e as Error).message
  }
}
function restorePlanning() {
  restoring = true
  const state = status.value.planning
  query.value = state.query
  selected.value = state.selected ? gridId(state.selected) : null
  startId.value = state.start ? gridId(state.start) : null
  mode.value = state.mode
  restoring = false
}
async function pickStart() {
  await attempt(async () => {
    status.value = await api.setMapPicking(!status.value.picking)
  })
}
let pan = { x: 0, y: 0 },
  fitted = false,
  scale = 20,
  frame = 0
let pointer: { x: number; y: number; panX: number; panY: number; moved: boolean } | null = null

async function attempt(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (e) {
    error.value = (e as Error).message
    status.value = await api.getMapStatus().catch(() => ({ ...status.value, enabled: false }))
    if (!status.value.enabled) {
      map.value = null
      route.value = null
    }
  } finally {
    busy.value = false
  }
}
async function chooseDirectory() {
  await attempt(async () => {
    const directory = await api.pickGameDirectory()
    if (directory) {
      status.value = await api.setMapDirectory(directory)
      restorePlanning()
    }
  })
}
async function enable(value: boolean) {
  await attempt(async () => {
    status.value = await api.setMapEnabled(value)
    if (status.value.consentToken) {
      consentToken.value = status.value.consentToken
      consentAcknowledged.value = false
      consentVisible.value = true
      return
    }
    if (status.value.enabled) await read()
    else {
      map.value = null
      route.value = null
      fitted = false
    }
  })
}
async function confirmConsent() {
  if (!consentAcknowledged.value || !consentToken.value) return
  await attempt(async () => {
    status.value = await api.confirmMapConsent(consentToken.value)
    consentVisible.value = false
    consentToken.value = ''
    if (status.value.enabled) await read()
  })
}
function cancelConsent() {
  if (busy.value) return
  consentVisible.value = false
  consentToken.value = ''
  void enable(false)
}
async function saveOverlay(patch: Partial<OverlayOptions>) {
  await attempt(async () => {
    status.value = await api.setMapOverlay(patch)
  })
}
function clearRoute() {
  route.value = null
  void api.clearMapRoute().catch((e) => {
    error.value = e.message
  })
}
async function read(reset = false) {
  const result = await api.readMap(reset)
  if (disposed) return
  map.value = result
  route.value = result.route ?? null
  if (!result.available) results.value = []
  if (!result.available) {
    route.value = null
    fitted = false
  }
  if (!fitted && result.nodes.length) {
    await nextTick()
    fit()
  }
  if (query.value.trim()) results.value = await api.searchMap(query.value.trim())
}
async function poll() {
  if (disposed) return
  if (!busy.value)
    await attempt(async () => {
      status.value = await api.getMapStatus()
      if (status.value.enabled) await read()
    })
  if (!disposed) timer = setTimeout(poll, 800)
}
async function plan() {
  if (!selectedNode.value) return
  const target = selectedNode.value.grid
  await attempt(async () => {
    await read()
    route.value = await api.planMapRoute({
      mode: mode.value,
      target,
      ...(mode.value === 'manual' && startId.value ? { start: parseGrid(startId.value)! } : {})
    })
    if (!route.value.found) message.warning(route.value.message)
  })
}
function fit() {
  const element = host.value
  if (!element || !nodes.value.length) return
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity
  for (const n of nodes.value) {
    minX = Math.min(minX, n.grid.x)
    maxX = Math.max(maxX, n.grid.x)
    minY = Math.min(minY, n.grid.y)
    maxY = Math.max(maxY, n.grid.y)
  }
  scale = Math.min(
    (element.clientWidth - 70) / Math.max(4, maxX - minX),
    (element.clientHeight - 70) / Math.max(4, maxY - minY)
  )
  zoom.value = 1
  pan = {
    x: element.clientWidth / 2 - ((minX + maxX) / 2) * scale,
    y: element.clientHeight / 2 - ((minY + maxY) / 2) * scale
  }
  fitted = true
  draw()
}
function changeZoom(
  factor: number,
  x = (host.value?.clientWidth || 0) / 2,
  y = (host.value?.clientHeight || 0) / 2
) {
  const next = Math.max(0.25, Math.min(12, zoom.value * factor)),
    ratio = next / zoom.value
  pan = { x: x - (x - pan.x) * ratio, y: y - (y - pan.y) * ratio }
  zoom.value = next
  draw()
}
function draw() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(paint)
}
function paint() {
  const element = canvas.value,
    parent = host.value
  if (!element || !parent) return
  const w = parent.clientWidth,
    h = parent.clientHeight,
    dpr = window.devicePixelRatio || 1
  element.width = Math.round(w * dpr)
  element.height = Math.round(h * dpr)
  const ctx = element.getContext('2d')
  if (!ctx) return
  ctx.scale(dpr, dpr)
  const dark = document.querySelector('.theme-root')?.classList.contains('dark')
  ctx.fillStyle = dark ? '#182021' : '#f5f8f7'
  ctx.fillRect(0, 0, w, h)
  const step = Math.max(24, scale * zoom.value * 5)
  ctx.strokeStyle = dark ? '#293235' : '#e6ece8'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let x = ((pan.x % step) + step) % step; x < w; x += step) {
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
  }
  for (let y = ((pan.y % step) + step) % step; y < h; y += step) {
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
  }
  ctx.stroke()
  if (!map.value?.available) return
  const point = (p: { x: number; y: number }) => ({
    x: p.x * scale * zoom.value + pan.x,
    y: p.y * scale * zoom.value + pan.y
  })
  const displayed = new Set(nodes.value.map((n) => n.id))
  ctx.strokeStyle = dark ? '#4a595d' : '#b9c8c1'
  ctx.beginPath()
  for (const e of map.value.edges) {
    if (!displayed.has(gridId(e.a)) || !displayed.has(gridId(e.b))) continue
    const a = point(e.a),
      b = point(e.b)
    ctx.moveTo(a.x, a.y)
    ctx.lineTo(b.x, b.y)
  }
  ctx.stroke()
  if (route.value?.found) {
    ctx.strokeStyle = dark ? '#f6cd74' : '#bb7112'
    ctx.lineWidth = 3
    ctx.beginPath()
    route.value.path.forEach((grid, i) => {
      const p = point(grid)
      if (i) ctx.lineTo(p.x, p.y)
      else ctx.moveTo(p.x, p.y)
    })
    ctx.stroke()
  }
  const matching = new Set(results.value)
  for (const n of nodes.value) {
    const p = point(n.grid)
    if (p.x < -30 || p.x > w + 30 || p.y < -30 || p.y > h + 30) continue
    const chosen = n.id === selected.value,
      current = !!map.value.currentNode && n.id === gridId(map.value.currentNode)
    ctx.fillStyle = current
      ? '#df6758'
      : n.canOpen
        ? '#268e6b'
        : n.state === 0
          ? '#697f99'
          : n.isHidden
            ? dark
              ? '#353840'
              : '#e8e4ef'
            : dark
              ? '#a1aca6'
              : '#fff'
    ctx.strokeStyle = chosen
      ? '#bc771b'
      : matching.has(n.id)
        ? '#ca7734'
        : dark
          ? '#b7c9bf'
          : '#6d8177'
    ctx.lineWidth = chosen || current ? 3 : 1.2
    ctx.beginPath()
    ctx.arc(p.x, p.y, chosen || current ? 7 : 4.5, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
    if (labels.value || chosen || current) {
      ctx.font = '11px "Segoe UI", "Microsoft YaHei UI", sans-serif'
      ctx.fillStyle = dark ? '#e4ebe7' : '#23332e'
      ctx.fillText(current ? `当前位置 · ${n.number}` : String(n.number), p.x + 10, p.y + 4)
    }
  }
}
function pointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  canvas.value?.setPointerCapture(event.pointerId)
  pointer = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y, moved: false }
}
function pointerMove(event: PointerEvent) {
  if (!pointer) return
  const dx = event.clientX - pointer.x,
    dy = event.clientY - pointer.y
  if (Math.abs(dx) + Math.abs(dy) > 4) pointer.moved = true
  pan = { x: pointer.panX + dx, y: pointer.panY + dy }
  draw()
}
function pointerUp(event: PointerEvent) {
  if (!pointer) return
  if (!pointer.moved && canvas.value) {
    const rect = canvas.value.getBoundingClientRect(),
      x = event.clientX - rect.left,
      y = event.clientY - rect.top
    let nearest: AtlasNode | undefined,
      distance = 16
    for (const n of nodes.value) {
      const d = Math.hypot(
        n.grid.x * scale * zoom.value + pan.x - x,
        n.grid.y * scale * zoom.value + pan.y - y
      )
      if (d < distance) {
        nearest = n
        distance = d
      }
    }
    if (nearest) selected.value = nearest.id
  }
  pointer = null
}
function centerCurrent() {
  const current = map.value?.currentNode
  if (!current || !host.value) return
  pan = {
    x: host.value.clientWidth / 2 - current.x * scale * zoom.value,
    y: host.value.clientHeight / 2 - current.y * scale * zoom.value
  }
  draw()
}
watch([map, route, selected, hidden, labels, results, () => app.settings.theme], draw)
watch(
  [mode, startId, selected],
  () => {
    void persistPlanning()
  },
  { flush: 'sync' }
)
watch(query, () => {
  resultPage.value = 1
  void persistPlanning()
  clearTimeout(debounce)
  const generation = ++queryGeneration
  if (!query.value.trim()) {
    results.value = []
    return
  }
  debounce = setTimeout(
    () =>
      void attempt(async () => {
        if (!status.value.enabled) return
        const found = await api.searchMap(query.value.trim())
        if (generation === queryGeneration) results.value = found
      }),
    350
  )
})
onMounted(async () => {
  observer = new ResizeObserver(draw)
  if (host.value) observer.observe(host.value)
  await attempt(async () => {
    status.value = await api.getMapStatus()
    restorePlanning()
    if (status.value.enabled) await read()
  })
  unsubscribe.push(
    api.onMapSelection((point) => {
      restoring = true
      startId.value = gridId(point)
      mode.value = 'manual'
      restoring = false
      message.success(`已设置游戏内起点 ${gridId(point)}`)
      void attempt(() => read())
    }),
    api.onMapPicking((picking) => {
      status.value.picking = picking
    })
  )
  void poll()
  draw()
})
onUnmounted(() => {
  disposed = true
  clearTimeout(timer)
  clearTimeout(debounce)
  cancelAnimationFrame(frame)
  observer?.disconnect()
  unsubscribe.forEach((stop) => stop())
  if (status.value.picking) void api.setMapPicking(false)
  if (consentToken.value) void api.setMapEnabled(false)
})
</script>

<template>
  <div class="world-map-page">
    <n-modal
      :show="consentVisible"
      preset="dialog"
      title="世界地图规划 · 风险确认"
      :mask-closable="false"
      :closable="!busy"
      :close-on-esc="!busy"
      style="width: 480px; max-width: calc(100vw - 32px)"
      @update:show="
        (value) => {
          if (!value) cancelConsent()
        }
      "
      @after-enter="cancelConsentButton?.$el?.focus()"
    >
      <template #icon><Icon icon="ph:warning-circle" /></template>
      <div class="atlas-consent-body">
        <n-tag type="warning" size="small" :bordered="false">仅限 POE2 国际服</n-tag>
        <p>{{ MAP_RISK }}</p>
        <p class="atlas-consent-note">
          此设备仅需确认一次。授权后会记住地图开关，下次启动恢复上次状态。
        </p>
        <n-checkbox v-model:checked="consentAcknowledged" :disabled="busy"
          >我已了解封号风险，自行承担后果，且仅在国际服使用</n-checkbox
        >
        <n-alert v-if="error" type="error" :show-icon="false">{{ error }}</n-alert>
      </div>
      <template #action
        ><n-button ref="cancelConsentButton" :disabled="busy" @click="cancelConsent">取消</n-button
        ><n-button
          type="warning"
          :loading="busy"
          :disabled="!consentAcknowledged || busy"
          @click="confirmConsent"
          >确认并开启</n-button
        ></template
      >
    </n-modal>
    <div class="atlas-risk">
      <Icon icon="ph:warning-circle" /><span
        >本功能需要读取内存，有封号风险，使用风险自行承担。仅限 POE2 国际服，其他服禁止使用。</span
      >
    </div>
    <div class="atlas-session">
      <div class="atlas-client">
        <n-tag size="small" :bordered="false" type="success">POE2 国际服专属</n-tag
        ><span :title="status.directory">{{ status.directory || '未选择世界地图客户端' }}</span>
      </div>
      <div class="atlas-session-actions">
        <n-button size="small" :disabled="busy || status.enabled" @click="chooseDirectory"
          ><template #icon><Icon icon="ph:folder-open" /></template>选择目录</n-button
        ><span class="atlas-switch-label">{{ status.enabled ? '读取中' : '已关闭' }}</span
        ><n-switch
          :value="status.enabled"
          :loading="busy"
          :disabled="!status.directory"
          aria-label="启用世界地图读取"
          @update:value="enable"
        />
      </div>
    </div>
    <n-alert v-if="error" type="error" class="mb-4" closable @close="error = ''">{{
      error
    }}</n-alert>
    <div class="atlas-overlay-controls">
      <label class="atlas-overlay-toggle"
        ><Icon icon="ph:stack-fill" /><b>游戏覆盖层</b
        ><n-switch
          :value="status.overlay.visible"
          size="small"
          :disabled="busy"
          aria-label="游戏覆盖层"
          @update:value="saveOverlay({ visible: $event })"
      /></label>
      <n-checkbox
        :checked="status.overlay.numbers"
        :disabled="busy"
        size="small"
        @update:checked="saveOverlay({ numbers: $event })"
        >节点编号</n-checkbox
      >
      <n-checkbox
        :checked="status.overlay.names"
        :disabled="busy"
        size="small"
        @update:checked="saveOverlay({ names: $event })"
        >节点名称</n-checkbox
      >
      <n-checkbox
        :checked="status.overlay.hidden"
        :disabled="busy"
        size="small"
        @update:checked="saveOverlay({ hidden: $event })"
        >隐藏节点标记</n-checkbox
      >
      <n-checkbox
        :checked="status.overlay.connections"
        :disabled="busy"
        size="small"
        @update:checked="saveOverlay({ connections: $event })"
        >连接线</n-checkbox
      >
      <label class="atlas-opacity"
        ><span>不透明度</span
        ><n-slider
          :value="status.overlay.opacity"
          :min="10"
          :max="100"
          :step="5"
          :disabled="busy"
          aria-label="覆盖层不透明度"
          @update:value="saveOverlay({ opacity: $event })"
      /></label>
      <label class="atlas-opacity"
        ><span>路线线宽</span
        ><n-slider
          :value="status.overlay.pathWidth"
          :min="1"
          :max="6"
          :step="1"
          :disabled="busy"
          aria-label="路线线宽"
          @update:value="saveOverlay({ pathWidth: $event })"
      /></label>
      <label class="atlas-route-color"
        ><span>路线颜色</span
        ><input
          type="color"
          :value="status.overlay.pathColor"
          :disabled="busy"
          aria-label="路线颜色"
          @change="saveOverlay({ pathColor: ($event.target as HTMLInputElement).value })"
      /></label>
      <n-checkbox
        :checked="status.overlay.allowBackground"
        :disabled="busy"
        size="small"
        @update:checked="saveOverlay({ allowBackground: $event })"
        >允许后台显示</n-checkbox
      >
      <span class="atlas-overlay-state">{{
        !status.enabled
          ? '未启动'
          : !status.overlay.visible
            ? '已隐藏'
            : map?.available && (map.gameWindow?.foreground || status.overlay.allowBackground)
              ? status.picking
                ? '正在选择起点 · 右键取消'
                : '游戏内显示中 · 鼠标穿透'
              : '等待游戏前台世界地图'
      }}</span>
    </div>
    <div class="atlas-layout">
      <section class="atlas-view" aria-label="世界地图">
        <div class="atlas-toolbar">
          <div class="atlas-tools">
            <n-button
              quaternary
              size="small"
              title="放大"
              aria-label="放大地图"
              @click="changeZoom(1.3)"
              ><Icon icon="ph:plus"
            /></n-button>
            <span class="atlas-zoom">{{ Math.round(zoom * 100) }}%</span>
            <n-button
              quaternary
              size="small"
              title="缩小"
              aria-label="缩小地图"
              @click="changeZoom(1 / 1.3)"
              ><Icon icon="ph:minus"
            /></n-button>
            <n-button
              quaternary
              size="small"
              title="适应全部节点"
              aria-label="适应全部节点"
              :disabled="!nodes.length"
              @click="fit"
              ><Icon icon="ph:corners-out"
            /></n-button>
            <n-button
              quaternary
              size="small"
              title="定位当前位置"
              aria-label="定位当前位置"
              :disabled="!map?.currentNode"
              @click="centerCurrent"
              ><Icon icon="ph:crosshair"
            /></n-button>
            <n-button
              quaternary
              size="small"
              title="重新识别地图布局"
              aria-label="重新识别地图布局"
              :disabled="!status.enabled || busy"
              @click="attempt(() => read(true))"
              ><Icon icon="ph:arrows-clockwise"
            /></n-button>
          </div>
          <div class="atlas-display">
            <n-checkbox v-model:checked="hidden" size="small">隐藏节点</n-checkbox
            ><n-checkbox v-model:checked="labels" size="small">编号</n-checkbox>
          </div>
        </div>
        <div ref="host" class="atlas-canvas-host">
          <canvas
            ref="canvas"
            aria-label="地图节点与规划路线"
            @pointerdown="pointerDown"
            @pointermove="pointerMove"
            @pointerup="pointerUp"
            @pointercancel="pointer = null"
            @wheel.prevent="
              changeZoom($event.deltaY > 0 ? 0.9 : 1.1, $event.offsetX, $event.offsetY)
            "
          />
          <div v-if="!map?.available" class="atlas-empty">
            <img :src="'./world-map/AtlasIconContentMapBoss.png'" alt="" />
            <h2>{{ status.enabled ? '等待世界地图' : '世界地图读取已关闭' }}</h2>
            <p>{{ status.enabled ? map?.reason || '正在连接客户端' : '未读取游戏内存' }}</p>
            <n-tag size="small" :bordered="false">{{
              status.authorized ? '风险已确认' : '尚未授权'
            }}</n-tag>
          </div>
        </div>
        <div class="atlas-legend">
          <span><i class="node-current" />当前位置</span><span><i class="node-open" />已开启</span
          ><span><i class="node-complete" />已完成</span><span><i class="node-locked" />未开启</span
          ><span><i class="node-hidden" />隐藏</span>
        </div>
        <div class="atlas-metrics">
          <span>{{ allNodes.length }} 节点 · {{ map?.edges.length || 0 }} 连接</span
          ><span v-if="map?.available"
            >读取 {{ Math.round(map.readMilliseconds) }} ms ·
            {{ map.unknownNameCount }} 个名称待确认</span
          ><span v-else>未连接地图</span>
        </div>
      </section>
      <aside class="atlas-planner">
        <div class="atlas-planner-heading">
          <h2>路线规划</h2>
          <Icon icon="ph:path" />
        </div>
        <label class="atlas-field-label" for="atlas-search">节点搜索</label>
        <n-input
          id="atlas-search"
          v-model:value="query"
          :maxlength="80"
          clearable
          placeholder="地图、类型、编号或坐标"
          :disabled="!status.enabled"
          ><template #prefix><Icon icon="ph:magnifying-glass" /></template
        ></n-input>
        <div class="atlas-search-header">
          <span>{{ query.trim() ? '搜索结果' : '已开启节点' }}</span
          ><span>{{ searchNodes.length }} 个</span>
        </div>
        <p class="atlas-distance-hint">
          {{ mode === 'manual' ? '以手动起点' : '以当前位置' }}计算直线距离 · 近到远
        </p>
        <div class="atlas-results" aria-label="地图搜索结果">
          <button
            v-for="node in pageNodes"
            :key="node.id"
            :class="['atlas-result', { selected: selected === node.id }]"
            @click="selected = node.id"
            @dblclick="plan"
          >
            <span class="atlas-node-number">{{ node.number }}</span
            ><span
              ><b>{{ node.displayName }}</b
              ><small>{{ node.stateText }} · {{ node.id }}</small
              ><small
                >{{ node.distance === null ? '距离未确认' : `${node.distance.toFixed(1)} 格` }} ·
                {{ node.delta }}</small
              ></span
            ><Icon v-if="selected === node.id" icon="ph:check" />
          </button>
          <p v-if="!searchNodes.length" class="atlas-no-results">
            {{ status.enabled ? '暂无匹配节点' : '尚无地图数据' }}
          </p>
        </div>
        <n-pagination
          v-if="pageCount > 1"
          v-model:page="resultPage"
          :page-count="pageCount"
          :page-slot="5"
          size="small"
          aria-label="搜索结果分页"
        />
        <div class="atlas-target">
          <span class="atlas-field-label">目标节点</span
          ><b>{{
            selectedNode
              ? `${selectedNode.number} · ${selectedNode.displayName}`
              : selected
                ? `${selected} · 等待节点加载`
                : '未选择目标'
          }}</b
          ><span v-if="selectedNode" class="atlas-target-meta"
            >{{ selectedNode.id }} · {{ selectedNode.stateText }}</span
          >
          <div v-if="selectedNode?.contentLabels.length" class="atlas-tags">
            <n-tag
              v-for="tag in selectedNode.contentLabels"
              :key="tag"
              size="small"
              :bordered="false"
              >{{ tag }}</n-tag
            >
          </div>
        </div>
        <n-button
          size="small"
          :disabled="busy || !map?.available || !status.overlay.visible"
          @click="pickStart"
          >{{ status.picking ? '取消游戏内选起点' : '游戏内选起点' }}</n-button
        >
        <p v-if="status.picking" class="atlas-distance-hint">
          切回游戏点击节点。右键取消，20 秒未选择会自动恢复鼠标穿透。
        </p>
        <label class="atlas-field-label" for="atlas-mode">起点</label>
        <n-select
          id="atlas-mode"
          v-model:value="mode"
          :options="[
            { label: '最优已开启节点', value: 'accessible' },
            { label: '当前位置', value: 'current' },
            { label: '自选节点', value: 'manual' }
          ]"
        />
        <div v-if="mode === 'manual'" class="atlas-manual-start">
          <span>{{ startId ? `起点 ${startId}` : '尚未设置起点' }}</span
          ><n-button size="small" :disabled="!selectedNode" @click="startId = selectedNode!.id"
            >设为起点</n-button
          >
        </div>
        <n-button
          class="atlas-plan-button"
          type="primary"
          :loading="busy"
          :disabled="
            !status.enabled ||
            !selectedNode ||
            (mode === 'manual' && !startId) ||
            (mode === 'current' && !map?.currentNode)
          "
          @click="plan"
          ><template #icon><Icon icon="ph:path" /></template>规划路线</n-button
        >
        <div v-if="route || status.planning.target" class="atlas-route-result" role="status">
          <b>{{
            route?.found
              ? `${route.path.length - 1} 段 · ${route.distance.toFixed(1)} 格`
              : route
                ? '无法规划'
                : '等待地图恢复'
          }}</b>
          <p>{{ route?.message || '已保存目标，地图加载后自动规划' }}</p>
          <ol v-if="route?.found">
            <li v-for="point in route.path" :key="gridId(point)">
              {{ nodeIndex.get(gridId(point))?.displayName || gridId(point) }}
              <small>{{ gridId(point) }}</small>
            </li>
          </ol>
          <n-button text size="small" @click="clearRoute">清除路线</n-button>
        </div>
      </aside>
    </div>
    <div class="atlas-footer">
      <span>{{
        map?.available
          ? `当前已加载节点 · ${new Date(map.capturedAt).toLocaleTimeString('zh-CN')}`
          : status.authorized
            ? '独立模块 · 记住上次开关'
            : '独立模块 · 首次默认关闭'
      }}</span
      ><n-button text size="small" @click="api.openCommunity('world-map')"
        >模块来源 <Icon icon="ph:arrow-square-out"
      /></n-button>
    </div>
  </div>
</template>
