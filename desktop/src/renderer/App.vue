<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import {
  NAlert,
  NButton,
  NCheckbox,
  NEmpty,
  NInput,
  NModal,
  NSelect,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage
} from 'naive-ui'
import { useAppStore } from './stores/app'
import type { AppSettings, GameVersion, Operation, OperationResult } from '../shared/types'
const HistoryPage = defineAsyncComponent(() => import('./components/HistoryPage.vue'))
const SettingsPage = defineAsyncComponent(() => import('./components/SettingsPage.vue'))
const desktop = window.desktop
const app = useAppStore(),
  message = useMessage(),
  dialog = useDialog()
const page = ref<'workspace' | 'history' | 'settings'>('workspace')
const pathsOpen = ref(false),
  manualPath = ref(''),
  searching = ref(false),
  cancelling = ref(false)
const historyDetail = ref<OperationResult | null>(null),
  followLog = ref(true),
  logElement = ref<HTMLElement>()
const title = computed(
  () =>
    ({
      workspace: '物价补丁',
      history: '运行记录',
      settings: '引用设置'
    })[page.value]
)
const names = { update: '更新物价', restore: '还原补丁', localize: 'POE1 汉化' }
const canUpdate = computed(
  () =>
    !!app.client &&
    !app.running &&
    !app.querying &&
    !app.leagueSaving &&
    (app.settings.patchScope === 'none'
      ? app.settings.gameVersion === 'poe2' && app.settings.islandRumourHints
      : app.selectedLeague === '__auto__' || !!app.league)
)
const sourceLabel = computed(() =>
  app.client?.isChina
    ? 'poecurrency.top'
    : app.settings.gameVersion === 'poe1'
      ? 'poe.ninja'
      : 'poe2scout + poe.ninja'
)
const latest = computed(() => app.state.history[0])
const phase = computed(() => {
  if (!app.running)
    return latest.value
      ? latest.value.cancelled
        ? '任务已取消'
        : latest.value.skipped
          ? '本轮已跳过'
          : latest.value.exitCode === 0
            ? '操作已完成'
            : '上次任务未完成'
      : '准备下一次冒险'
  return (
    app.events
      .flatMap((e) => e.message.split(/\r?\n/))
      .filter((line) => line.trim() && /==>|进度|正在|提取|生成|校验|下载|安装/.test(line))
      .at(-1)
      ?.replace(/^==>\s*/, '')
      .slice(0, 90) || '正在执行，请稍候…'
  )
})
const localeDate = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false })
async function attempt(action: () => Promise<unknown>) {
  try {
    await action()
  } catch (e) {
    message.error(String((e as Error).message || e), { duration: 6000 })
  }
}
async function save(patch: Partial<AppSettings>) {
  await attempt(() => app.save(patch))
}
async function setVersion(version: GameVersion) {
  await attempt(async () => {
    await app.save({
      gameVersion: version,
      patchScope:
        app.settings.patchScope === 'none' && version === 'poe1' ? 'all' : app.settings.patchScope
    })
    app.clients = []
    await app.inspect()
  })
}
async function browse() {
  await attempt(async () => {
    const path = await desktop.pickGameDirectory()
    if (path) {
      await app.selectDirectory(path)
      pathsOpen.value = false
    }
  })
}
async function discover() {
  searching.value = true
  await attempt(async () => {
    await app.discover()
    pathsOpen.value = true
    if (!app.clients.length) message.info('未发现客户端，可以手动选择游戏目录')
  })
  searching.value = false
}
async function execute(operation: Operation) {
  page.value = 'workspace'
  await attempt(async () => {
    const result = await app.run(operation)
    if (result.cancelled) message.warning('任务已停止，请确认游戏文件完整性')
    else if (result.exitCode === 0) message.success(`${names[operation]}完成`)
    else message.error('操作未完成，请查看运行日志', { duration: 6000 })
  })
}
function confirmOperation(operation: Operation) {
  dialog.warning({
    title:
      operation === 'update'
        ? '确认更新物价'
        : operation === 'restore'
          ? '确认还原补丁'
          : '确认汉化 POE1',
    content: `${app.client?.displayName || ''}\n${app.client?.path || ''}\n\n${operation === 'restore' ? `将用此客户端的专属基线还原补丁。${app.settings.autoUpdate ? '每小时自动更新仍保持开启，下一轮会按最近成功的配置重新应用补丁。' : ''}` : operation === 'localize' ? '将下载并校验 POE1 国际服汉化工具。完成后在游戏内选择法文国旗。' : '将获取所选赛季价格并写入当前游戏客户端。'}请确认游戏已关闭。`,
    positiveText: '确认执行',
    negativeText: '返回',
    onPositiveClick: () => {
      void execute(operation)
    }
  })
}
function stop() {
  dialog.warning({
    title: '停止当前任务？',
    content:
      '如果正在写入游戏文件，强制停止可能留下未完成的补丁。停止后请先尝试还原；无法还原时使用游戏平台校验文件。',
    positiveText: '停止任务',
    negativeText: '继续等待',
    onPositiveClick: () =>
      attempt(async () => {
        if (!app.state.active) return
        cancelling.value = true
        try {
          if (!(await desktop.cancelOperation(app.state.active.runId)))
            throw new Error('无法停止进程，请等待任务结束')
        } finally {
          cancelling.value = false
        }
      })
  })
}
watch(
  () => app.logText,
  async () => {
    if (followLog.value) {
      await nextTick()
      if (logElement.value) logElement.value.scrollTop = logElement.value.scrollHeight
    }
  }
)
onMounted(() => app.init())
onUnmounted(() => app.dispose())
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <img src="./icon.png" alt="" />
        <div><strong>物价补丁</strong><span>PATH OF EXILE 1 / 2</span></div>
      </div>
      <div class="nav-caption">工作空间</div>
      <nav aria-label="主导航">
        <button :class="['nav-item', { active: page === 'workspace' }]" @click="page = 'workspace'">
          <Icon icon="ph:squares-four" />物价补丁
        </button>
        <button :class="['nav-item', { active: page === 'history' }]" @click="page = 'history'">
          <Icon icon="ph:clock-counter-clockwise" />运行记录<span
            v-if="app.state.history.length"
            class="count"
            >{{ app.state.history.length }}</span
          >
        </button>
        <button :class="['nav-item', { active: page === 'settings' }]" @click="page = 'settings'">
          <Icon icon="ph:sliders-horizontal" />引用设置
        </button>
      </nav>
      <div class="sidebar-bottom">
        <div class="engine-label">
          <Icon icon="ph:shield-check" /><span>本地执行 · 自动备份</span>
        </div>
        <div class="version-line">
          <span>桌面版 v{{ app.state.version }}</span
          ><span>Windows</span>
        </div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="breadcrumb">
          工作空间<Icon icon="ph:caret-right" /><b>{{ title }}</b>
        </div>
        <span :class="['live-status', { running: app.running }]">{{
          app.running ? '任务执行中' : '本地工作台'
        }}</span>
      </header>
      <div v-if="app.loading" class="loading-state">
        <n-spin size="large" />
        <p>正在加载工作台…</p>
      </div>
      <div v-else class="page-body">
        <div class="page-heading">
          <div>
            <h1>{{ title }}</h1>
            <p>
              {{
                page === 'workspace'
                  ? '让价值一目了然，把时间留给探索。'
                  : page === 'history'
                    ? '每次更新与还原，都有迹可循。'
                    : '按你的习惯，安排这间工作台。'
              }}
            </p>
          </div>
          <n-tag v-if="app.running" type="warning" :bordered="false"
            >正在执行
            {{ app.state.active ? names[app.state.active.request.operation] : '任务' }}</n-tag
          >
        </div>
        <n-alert v-if="app.error" class="mb-4" type="error" closable @close="app.error = ''">{{
          app.error
        }}</n-alert>
        <template v-if="page === 'workspace'">
          <section class="client-panel">
            <div class="client-title">
              <div class="client-icon"><Icon icon="ph:game-controller" /></div>
              <div>
                <span class="small-label">当前客户端</span>
                <h2>
                  {{ app.settings.gameVersion === 'poe2' ? 'Path of Exile 2' : 'Path of Exile' }}
                </h2>
              </div>
              <div class="game-switch" aria-label="游戏版本">
                <button
                  :class="{ selected: app.settings.gameVersion === 'poe2' }"
                  :disabled="app.running || app.querying"
                  @click="setVersion('poe2')"
                >
                  POE 2</button
                ><button
                  :class="{ selected: app.settings.gameVersion === 'poe1' }"
                  :disabled="app.running || app.querying"
                  @click="setVersion('poe1')"
                >
                  POE 1
                </button>
              </div>
            </div>
            <div class="client-path">
              <Icon icon="ph:folder-open" /><span :title="app.directory">{{
                app.directory || '选择游戏目录，开始配置你的物价补丁'
              }}</span
              ><n-button size="small" :disabled="app.running || app.querying" @click="browse">{{
                app.directory ? '更换目录' : '选择目录'
              }}</n-button
              ><n-button
                size="small"
                secondary
                :loading="searching"
                :disabled="app.running || app.querying"
                @click="discover"
                >自动识别</n-button
              >
            </div>
            <div v-if="app.client" class="client-meta">
              <n-tag size="small" type="success" :bordered="false">目录已识别</n-tag
              ><span>{{ app.client.displayName }}</span
              ><span>{{ app.client.language }}</span>
            </div>
            <div v-else class="client-meta">
              <n-spin v-if="app.querying" size="small" /><span>{{
                app.querying
                  ? '正在识别客户端，请稍候…'
                  : '支持官服 GGPK、Steam / Epic 与国服 WeGame'
              }}</span>
            </div>
          </section>
          <div class="workspace-grid">
            <section class="panel configuration">
              <div class="panel-heading">
                <h2>补丁内容</h2>
                <span>按需选择</span>
              </div>
              <div class="form-field">
                <label for="league">价格赛季</label>
                <div class="field-inline">
                  <n-select
                    id="league"
                    :value="app.selectedLeague"
                    @update:value="app.selectLeague"
                    :options="app.leagueOptions"
                    :loading="app.leagueLoading"
                    :disabled="app.running || !app.client || app.leagueLoading || app.leagueSaving"
                    :placeholder="app.client ? '选择价格赛季' : '先选择客户端'"
                  /><n-button
                    quaternary
                    circle
                    :loading="app.leagueLoading"
                    :disabled="app.running || !app.client || app.leagueLoading"
                    title="刷新赛季"
                    aria-label="刷新赛季"
                    @click="app.refreshLeagues"
                    ><Icon icon="ph:arrows-clockwise"
                  /></n-button>
                </div>
                <p class="field-help">
                  {{
                    app.client ? `价格来源：${sourceLabel}` : '识别客户端后，自动加载对应服区赛季。'
                  }}
                </p>
              </div>
              <n-alert v-if="app.leagueNotice" type="info" class="mb-4">{{
                app.leagueNotice
              }}</n-alert>
              <fieldset class="scope-field" :disabled="app.running">
                <legend>更新范围</legend>
                <div class="scope-list">
                  <label
                    v-for="item in [
                      ['all', '通货与传奇', '完整显示物品参考价格'],
                      ['currency', '仅通货', '通货、碑牌词缀与可交易物品'],
                      ['uniques', '仅传奇', '传奇装备参考价格']
                    ] as const"
                    :key="item[0]"
                    :class="['scope-option', { selected: app.settings.patchScope === item[0] }]"
                    ><input
                      type="radio"
                      name="scope"
                      :checked="app.settings.patchScope === item[0]"
                      @change="save({ patchScope: item[0] })" />
                    <div>
                      <b>{{ item[1] }}</b
                      ><span>{{ item[2] }}</span>
                    </div>
                    <Icon
                      v-if="app.settings.patchScope === item[0]"
                      icon="ph:check-circle" /></label
                  ><label
                    v-if="app.settings.gameVersion === 'poe2'"
                    :class="[
                      'scope-option compact',
                      { selected: app.settings.patchScope === 'none' }
                    ]"
                    ><input
                      type="radio"
                      name="scope"
                      :checked="app.settings.patchScope === 'none'"
                      @change="save({ patchScope: 'none', islandRumourHints: true })"
                    />
                    <div><b>仅岛屿传言提示</b></div></label
                  >
                </div>
              </fieldset>
              <div v-if="app.settings.gameVersion === 'poe2' && app.settings.patchScope !== 'uniques'" class="tablet-source-note">
                <Icon icon="ph:scroll" />
                <div><b>碑牌词缀标价已包含</b><span>获取失败会自动重试，仍不可用时跳过碑牌层，不影响其他价格。</span></div>
              </div>
              <div v-if="app.settings.gameVersion === 'poe2'" class="option-row">
                <div>
                  <b>岛屿传言地图提示</b>
                  <p>在传言名称中追加对应地图</p>
                </div>
                <n-switch
                  :value="app.settings.islandRumourHints"
                  :disabled="app.running || app.settings.patchScope === 'none'"
                  aria-label="岛屿传言地图提示"
                  @update:value="save({ islandRumourHints: $event })"
                />
              </div>
              <div v-if="app.settings.gameVersion === 'poe1'" class="form-field">
                <label>POE1 显示语言</label
                ><n-select
                  :value="app.settings.languageMode"
                  :disabled="app.running"
                  :options="[
                    { label: '自动识别', value: 'auto' },
                    { label: '汉化补丁', value: 'localization' },
                    { label: '简体中文（缺失时汉化）', value: 'zh-CN' },
                    { label: '繁体中文', value: 'zh-TW' },
                    { label: '跟随游戏配置', value: 'config' }
                  ]"
                  @update:value="
                    attempt(async () => {
                      await app.save({ languageMode: $event })
                      await app.inspect()
                    })
                  "
                />
              </div>
              <div class="action-note">
                <Icon icon="ph:info" /><span>请先关闭游戏。修改游戏文件存在封号风险。</span>
              </div>
            </section>
            <section class="panel activity-panel">
              <div class="panel-heading">
                <h2>执行动态</h2>
                <n-tag
                  size="small"
                  :type="app.running ? 'info' : latest?.exitCode === 0 ? 'success' : 'default'"
                  :bordered="false"
                  >{{ app.running ? '运行中' : '就绪' }}</n-tag
                >
              </div>
              <div :class="['activity-status', { working: app.running }]">
                <div class="activity-symbol">
                  <n-spin v-if="app.running" size="small" /><Icon
                    v-else
                    :icon="
                      latest
                        ? latest.exitCode === 0 && !latest.cancelled
                          ? 'ph:check-circle'
                          : 'ph:warning-circle'
                        : 'ph:terminal-window'
                    "
                  />
                </div>
                <div>
                  <h3>{{ phase }}</h3>
                  <p>
                    {{
                      app.running
                        ? '后台执行中，可以切换页面查看其他信息。'
                        : latest
                          ? `${names[latest.operation]} · ${localeDate(latest.startedAt)}`
                          : '任务开始后，进度和结果会在这里实时显示。'
                    }}
                  </p>
                </div>
              </div>
              <div class="log-toolbar">
                <span><Icon icon="ph:terminal-window" />运行日志</span>
                <div>
                  <n-checkbox v-model:checked="followLog" size="small">跟随输出</n-checkbox
                  ><n-button
                    text
                    size="small"
                    :disabled="!app.logText"
                    @click="attempt(() => desktop.exportLog(app.logText))"
                    >导出</n-button
                  >
                </div>
              </div>
              <div ref="logElement" class="log-view" role="log" aria-label="运行日志" tabindex="0">
                <pre v-if="app.logText">{{ app.logText }}</pre>
                <div v-else class="log-placeholder">
                  <Icon icon="ph:terminal-window" /><b>等待任务开始</b>
                  <p>选择客户端与补丁内容，然后点击开始更新。</p>
                  <span>完整日志保存在本机，窗口显示最近输出。</span>
                </div>
              </div>
              <div class="activity-footer">
                <span>{{
                  app.running ? '请勿启动游戏或移动客户端目录' : '价格仅供参考，以实际交易为准'
                }}</span
                ><n-button
                  v-if="app.running"
                  size="small"
                  type="warning"
                  secondary
                  :loading="cancelling"
                  @click="stop"
                  >停止任务</n-button
                ><n-button
                  v-else
                  size="small"
                  text
                  @click="attempt(() => desktop.openFolder('logs'))"
                  >打开日志 <Icon icon="ph:arrow-square-out"
                /></n-button>
              </div>
            </section>
          </div>
        </template>
        <HistoryPage v-else-if="page === 'history'" @select="historyDetail = $event" />
        <template v-else>
          <SettingsPage />
        </template>
        <footer class="page-footer">
          <span>POE {{ app.settings.gameVersion === 'poe2' ? '2' : '1' }} 物价补丁</span
          ><span>价格标注 · 客户端独立备份 · 随时还原</span>
        </footer>
      </div>
      <div
        v-if="page === 'workspace' && !app.loading"
        class="persistent-actions"
        aria-label="补丁操作"
      >
        <div class="persistent-status">
          <Icon icon="ph:shield-check" /><span>{{
            app.client ? app.client.displayName : '先选择游戏客户端'
          }}</span>
        </div>
        <div class="flex gap-2">
          <n-button
            v-if="app.settings.gameVersion === 'poe1'"
            :disabled="app.running || app.querying || !app.client || app.client.isChina"
            :loading="app.state.active?.request.operation === 'localize'"
            @click="confirmOperation('localize')"
            >一键汉化 POE1</n-button
          >
          <n-button
            secondary
            :disabled="app.running || !app.client"
            @click="confirmOperation('restore')"
            ><template #icon><Icon icon="ph:arrow-counter-clockwise" /></template>还原补丁</n-button
          >
          <n-button
            type="primary"
            :disabled="!canUpdate"
            :loading="app.running"
            @click="confirmOperation('update')"
            ><template #icon><Icon icon="ph:play-fill" /></template
            >{{ app.running ? '任务执行中' : '开始更新物价' }}</n-button
          >
        </div>
      </div>
    </main>
  </div>
  <n-modal v-model:show="pathsOpen" preset="card" title="选择游戏目录" class="app-modal"
    ><p class="modal-hint">检测到多个客户端时，请选择本次要操作的目录。</p>
    <div v-for="client in app.clients" :key="client.path" class="candidate">
      <div>
        <b>{{ client.displayName }}</b>
        <p>{{ client.path }}</p>
      </div>
      <n-button
        :disabled="app.running"
        @click="
          attempt(async () => {
            await app.selectDirectory(client.path)
            pathsOpen = false
          })
        "
        >选择</n-button
      >
    </div>
    <label class="form-label">手动输入游戏根目录</label
    ><n-input v-model:value="manualPath" placeholder="例如 D:\Games\Path of Exile 2" />
    <div class="modal-actions">
      <n-button @click="browse">浏览文件夹</n-button
      ><n-button
        type="primary"
        :disabled="!manualPath.trim() || app.running"
        @click="
          attempt(async () => {
            await app.selectDirectory(manualPath)
            pathsOpen = false
          })
        "
        >使用此目录</n-button
      >
    </div></n-modal
  >
  <n-modal
    :show="!!historyDetail"
    preset="card"
    title="运行详情"
    class="app-modal"
    @update:show="historyDetail = null"
    ><template v-if="historyDetail"
      ><p>
        {{ names[historyDetail.operation] }} · {{ localeDate(historyDetail.startedAt) }} · 退出码
        {{ historyDetail.exitCode }}
      </p>
      <p class="detail-path">{{ historyDetail.gameDirectory }}</p>
      <pre class="detail-log">{{
        historyDetail.stdout + '\n' + historyDetail.stderr || '无输出'
      }}</pre>
      <n-button @click="attempt(() => desktop.exportLog(JSON.stringify(historyDetail, null, 2)))"
        >导出本次记录</n-button
      ></template
    ></n-modal
  >
</template>
