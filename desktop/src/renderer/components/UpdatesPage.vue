<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { NAlert, NButton, NModal, NProgress, useMessage } from 'naive-ui'
import type { SoftwareUpdateState } from '../../shared/software-update'
import codeImage from '../assets/appreciation-code.png'
import fullImage from '../assets/appreciation-full.jpg'
const props = defineProps<{ busy: boolean }>()
const message = useMessage()
const desktop = window.desktop
const state = ref<SoftwareUpdateState>()
const imageOpen = ref(false)
const acting = ref(false)
let detach: (() => void) | undefined
const working = computed(
  () =>
    acting.value || ['checking', 'downloading', 'installing'].includes(state.value?.status || '')
)
const available = computed(() => ['available', 'ready'].includes(state.value?.status || ''))
const percent = computed(() =>
  state.value?.totalBytes
    ? Math.min(100, Math.floor((state.value.downloadedBytes / state.value.totalBytes) * 100))
    : 0
)
const size = (bytes: number) =>
  bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`
const updateLabel = computed(() => {
  if (state.value?.status === 'downloading') return '正在下载更新'
  if (state.value?.status === 'installing') return '正在重启安装'
  if (state.value?.status === 'ready') return '重启并更新'
  return '立即更新'
})
const displayNewRelease = computed(
  () =>
    !!state.value?.release &&
    state.value.release.version !== state.value.currentVersion &&
    state.value.status !== 'current'
)
async function attempt(action: () => Promise<unknown>) {
  try {
    await action()
  } catch (error) {
    message.error((error as Error).message || String(error))
  }
}
async function check() {
  await attempt(async () => {
    state.value = await window.desktop.checkSoftwareUpdate()
  })
}
async function update() {
  acting.value = true
  await attempt(async () => {
    if (state.value?.status === 'available')
      state.value = await window.desktop.downloadSoftwareUpdate()
    if (state.value?.status === 'ready' && !props.busy)
      state.value = await window.desktop.installSoftwareUpdate()
  })
  acting.value = false
}
async function copyGroup() {
  await attempt(async () => {
    await window.desktop.copyFeedbackGroup()
    message.success('已复制群号 168887742')
  })
}
onMounted(async () => {
  detach = window.desktop.onSoftwareUpdate((value) => {
    state.value = value
  })
  await attempt(async () => {
    state.value = await window.desktop.getSoftwareUpdate()
  })
  if (state.value?.status === 'idle') void check()
})
onUnmounted(() => detach?.())
</script>

<template>
  <section class="updates-page" aria-label="软件版本与更新">
    <div class="updates-layout">
      <div class="release-panel">
        <div class="release-heading">
          <div>
            <span class="release-caption">当前版本</span>
            <h2>v{{ state?.currentVersion || '…' }}</h2>
          </div>
          <n-button
            secondary
            :loading="state?.status === 'checking'"
            :disabled="working || state?.status === 'unconfigured' || state?.status === 'ready'"
            @click="check"
          >
            <template #icon><Icon icon="ph:arrows-clockwise" /></template>检查新版本
          </n-button>
        </div>
        <div class="update-status" role="status" aria-live="polite">
          <Icon
            :icon="
              available ? 'ph:download-simple' : state?.status === 'error' ? 'ph:info' : 'ph:check'
            "
          />
          <span>{{ state?.message || '正在读取版本信息…' }}</span>
        </div>
        <div class="release-notes-scroll" tabindex="0" aria-label="版本更新内容">
          <div v-if="displayNewRelease" class="new-release">
            <h3>新版本 v{{ state?.release?.version }}</h3>
            <ul>
              <li v-for="note in state?.release?.notes" :key="note">{{ note }}</li>
            </ul>
          </div>
          <div class="current-release">
            <h3>本次更新内容</h3>
            <ul>
              <li v-for="note in state?.currentNotes" :key="note">{{ note }}</li>
            </ul>
          </div>
        </div>
        <button class="feedback-link" @click="copyGroup" title="复制群号">
          <Icon icon="ph:chat-circle-dots" />
          <span>聊天/bug反馈群:<strong>168887742</strong></span>
          <Icon icon="ph:copy" />
        </button>
      </div>
      <aside class="appreciation-panel" aria-label="自愿赞赏">
        <Icon class="appreciation-heart" icon="ph:heart" />
        <h2>本软件完全免费禁止倒卖</h2>
        <p>喜欢的可以投喂一下</p>
        <button class="appreciation-image" @click="imageOpen = true" aria-label="查看完整赞赏码">
          <img :src="codeImage" width="620" height="620" alt="作者的微信赞赏码" />
        </button>
        <span class="appreciation-hint">微信扫一扫 · 自愿支持</span>
      </aside>
    </div>
    <div class="software-update-actions">
      <div class="software-update-summary">
        <h3>
          {{
            available
              ? '新版本已准备好'
              : state?.status === 'downloading'
                ? '正在获取更新包'
                : '保持软件为最新版本'
          }}
        </h3>
        <p v-if="props.busy">物价任务完成后即可安装软件更新。</p>
        <p v-else-if="state?.totalBytes">
          更新安装包 {{ size(state.totalBytes) }}。下载完成后自动重启。
        </p>
        <p v-else>有新版本时，可在这里一键下载并安装。</p>
        <n-progress
          v-if="state?.status === 'downloading'"
          type="line"
          :percentage="percent"
          :height="5"
          :show-indicator="false"
          aria-label="更新包下载进度"
        />
        <span v-if="state?.status === 'downloading'" class="download-amount"
          >{{ size(state.downloadedBytes) }} / {{ size(state.totalBytes) }}</span
        >
      </div>
      <div class="software-update-buttons">
        <n-button
          v-if="state?.status === 'downloading'"
          quaternary
          @click="attempt(() => desktop.cancelSoftwareUpdate())"
          >取消下载</n-button
        >
        <n-button
          type="primary"
          size="large"
          :disabled="!available || props.busy || working"
          :loading="['downloading', 'installing'].includes(state?.status || '')"
          @click="update"
        >
          <template #icon><Icon icon="ph:download-simple" /></template>{{ updateLabel }}
        </n-button>
      </div>
    </div>
    <n-alert v-if="state?.status === 'error'" type="warning" :show-icon="false"
      >{{ state.message }}。请稍后点击“检查新版本”重试。</n-alert
    >
  </section>
  <n-modal v-model:show="imageOpen" preset="card" title="微信赞赏码" class="appreciation-modal">
    <img :src="fullImage" width="1210" height="1210" alt="完整的作者微信赞赏码，支持完全自愿" />
  </n-modal>
</template>

<style src="./updates.css"></style>
