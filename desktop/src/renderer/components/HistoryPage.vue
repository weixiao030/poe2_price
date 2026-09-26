<script setup lang="ts">
import { useAppStore } from '../stores/app'
import { useMessage } from 'naive-ui'
import { Icon } from '@iconify/vue'
import { operationWarning } from '../../shared/operation-outcome'
const app = useAppStore(),
  message = useMessage(),
  desktop = window.desktop
async function attempt(action: () => Promise<unknown>) {
  try {
    await action()
  } catch (e) {
    message.error(String((e as Error).message || e), { duration: 6000 })
  }
}
import { NButton, NEmpty, NTag } from 'naive-ui'
import type { OperationResult } from '../../shared/types'
const emit = defineEmits<{ select: [item: OperationResult] }>()
const names = { update: '更新物价', restore: '还原补丁', localize: 'POE1 汉化' }
const localeDate = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false })
</script>
<template>
  <section class="panel history-panel">
    <div class="panel-heading">
      <h2>最近 50 次任务</h2>
      <n-button size="small" @click="attempt(() => desktop.openFolder('logs'))"
        >打开完整日志</n-button
      >
    </div>
    <n-empty
      v-if="!app.state.history.length"
      class="empty-history"
      description="还没有运行记录，完成一次更新后会显示在这里。"
    />
    <div v-else class="history-list">
      <button
        v-for="item in app.state.history"
        :key="item.runId"
        class="history-row"
        @click="emit('select', item)"
      >
        <Icon
          :class="
            operationWarning(item)
              ? 'warning-icon'
              : item.exitCode === 0 && !item.cancelled
                ? 'success-icon'
                : 'failure-icon'
          "
          :icon="
            item.exitCode === 0 && !item.cancelled && !operationWarning(item)
              ? 'ph:check-circle'
              : 'ph:warning-circle'
          "
        />
        <div>
          <b
            >{{ names[item.operation] }}
            <n-tag size="small" :bordered="false">{{ item.gameVersion.toUpperCase() }}</n-tag></b
          ><span>{{ operationWarning(item) || item.gameDirectory }}</span>
        </div>
        <div class="history-meta">
          <b
            >{{
              item.cancelled
                ? '已停止'
                : item.skipped
                  ? '已跳过'
                  : operationWarning(item)
                    ? '部分完成'
                    : item.exitCode === 0
                      ? '成功'
                      : '失败'
            }}
            · {{ (item.durationMs / 1000).toFixed(1) }} 秒</b
          ><span>{{ localeDate(item.startedAt) }} · {{ item.automatic ? '自动' : '手动' }}</span>
        </div>
        <Icon icon="ph:caret-right" />
      </button>
    </div>
  </section>
</template>
