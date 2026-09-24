<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import type { SoftwareUpdateState } from '../../shared/software-update'

const emit = defineEmits<{ open: [] }>()
const version = ref('')
const saving = ref(false)
const error = ref('')
const notice = ref<HTMLElement>()
let detach: (() => void) | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let hovered = false

function pause() {
  clearTimeout(timer)
}
function hover(value: boolean) {
  hovered = value
  resume()
}
function focusOut() {
  queueMicrotask(resume)
}
function resume() {
  pause()
  if (
    version.value &&
    !document.hidden &&
    !hovered &&
    !saving.value &&
    !error.value &&
    !notice.value?.contains(document.activeElement)
  )
    timer = setTimeout(() => {
      void dismiss()
    }, 3000)
}
function receive(state: SoftwareUpdateState) {
  const next = state.startupNotificationVersion || ''
  if (version.value === next) return
  version.value = next
  error.value = ''
  resume()
}
async function dismiss(ignore = false) {
  if (!version.value || saving.value) return
  pause()
  saving.value = true
  try {
    await window.desktop.dismissSoftwareUpdateNotice(version.value, ignore)
    version.value = ''
  } catch {
    error.value = '未能保存，请重试'
  } finally {
    saving.value = false
  }
}
async function open() {
  emit('open')
  await dismiss()
}
onMounted(async () => {
  detach = window.desktop.onSoftwareUpdate(receive)
  document.addEventListener('visibilitychange', resume)
  try {
    const state = await window.desktop.getSoftwareUpdate()
    if (!disposed) receive(state)
  } catch {
    /* A notice never blocks the workspace. */
  }
})
onUnmounted(() => {
  disposed = true
  pause()
  detach?.()
  document.removeEventListener('visibilitychange', resume)
})
</script>

<template>
  <aside
    v-if="version"
    ref="notice"
    class="update-notice"
    aria-label="发现软件更新"
    @mouseenter="hover(true)"
    @mouseleave="hover(false)"
    @focusin="pause"
    @focusout="focusOut"
    @keydown.esc="dismiss()"
  >
    <div class="update-notice-heading">
      <Icon icon="ph:download-simple" aria-hidden="true" />
      <strong role="status">新版本 v{{ version }} 可用</strong>
      <button class="notice-close" aria-label="关闭更新提醒" :disabled="saving" @click="dismiss()">
        <Icon icon="ph:x" aria-hidden="true" />
      </button>
    </div>
    <p>有空时再更新，当前操作可继续。</p>
    <div class="update-notice-actions">
      <button class="notice-view" :disabled="saving" @click="open">查看更新</button>
      <button :disabled="saving" @click="dismiss(true)">本次更新不再提醒</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
  </aside>
</template>

<style scoped>
.update-notice {
  position: fixed;
  top: 72px;
  right: 24px;
  z-index: 100;
  width: min(344px, calc(100vw - 32px));
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
}
.update-notice-heading {
  display: flex;
  align-items: center;
  gap: 8px;
}
.update-notice-heading > svg {
  color: var(--accent);
  flex: none;
  font-size: 18px;
}
.update-notice-heading strong {
  flex: 1;
  overflow-wrap: anywhere;
  font-size: 14px;
}
.update-notice p {
  margin-top: 8px;
  color: var(--muted);
  line-height: 1.6;
}
.update-notice-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.update-notice button {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: 4px 0;
}
.update-notice button:hover {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 3px;
}
.update-notice button:disabled {
  opacity: 0.6;
}
.update-notice .notice-view {
  color: var(--accent);
  font-weight: 600;
}
.update-notice .notice-close {
  padding: 4px;
  display: flex;
  font-size: 18px;
}
</style>
