<script setup lang="ts">
import { useAppStore } from '../stores/app'
import { useMessage } from 'naive-ui'
import { Icon } from '@iconify/vue'
import { ref } from 'vue'
import './settings.css'
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
import { NButton, NSelect, NSwitch, NSlider } from 'naive-ui'
import type { AppSettings } from '../../shared/types'
async function save(patch: Partial<AppSettings>) {
  await attempt(() => app.save(patch))
}
const localeDate = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false })
const cleaning = ref(false)
const cleanupResult = ref('')
async function cleanup(kind: 'cache' | 'logs') {
  cleaning.value = true
  await attempt(async () => {
    const result = await desktop.cleanupFiles(kind, true)
    if (result.cancelled) return
    cleanupResult.value = `已清理 ${result.files} 个文件，释放 ${(result.bytes / 1024 / 1024).toFixed(2)} MB${result.skipped ? `，${result.skipped} 项受保护或被占用，已跳过` : ''}。`
    message.success(cleanupResult.value)
  })
  cleaning.value = false
}
</script>
<template>
  <section class="panel settings-panel">
    <div class="panel-heading">
      <h2>外观与后台运行</h2>
      <Icon icon="ph:sliders-horizontal" />
    </div>
    <div class="settings-row background-setting">
      <div>
        <b>自定义背景图片</b>
        <p>选择本地 JPG 或 PNG，图片会保存到应用中。</p>
        <p>支持不超过 20 MB 的图片，自动缩小以减少内存占用。</p>
      </div>
      <div class="background-controls">
        <img
          v-if="app.background"
          :src="app.background"
          class="background-preview"
          alt="当前背景预览"
        />
        <div class="flex gap-2">
          <n-button
            @click="
              attempt(async () => {
                const value = await desktop.chooseBackground()
                if (value) {
                  app.background = value
                  message.success('背景图片已保存')
                }
              })
            "
            >{{ app.background ? '更换背景图片' : '选择背景图片' }}</n-button
          >
          <n-button
            :disabled="!app.background"
            @click="
              attempt(async () => {
                await desktop.clearBackground()
                app.background = null
                message.success('已恢复默认背景')
              })
            "
            >恢复默认</n-button
          >
        </div>
      </div>
    </div>
    <div v-if="app.background" class="settings-row">
      <div>
        <b>背景浓度</b>
        <p>降低浓度可以让文字更清晰。</p>
      </div>
      <n-slider
        class="background-slider"
        :value="app.settings.backgroundOpacity"
        :min="0"
        :max="60"
        :step="1"
        :disabled="app.running"
        aria-label="背景浓度"
        @update:value="save({ backgroundOpacity: $event })"
      />
    </div>
    <div class="settings-row">
      <div>
        <b>界面主题</b>
        <p>选择适合当前环境的外观。</p>
      </div>
      <n-select
        class="theme-select"
        :value="app.settings.theme"
        :disabled="app.running"
        :options="[
          { label: '浅色', value: 'light' },
          { label: '深色', value: 'dark' },
          { label: '跟随系统', value: 'system' }
        ]"
        @update:value="save({ theme: $event })"
      />
    </div>
    <div class="settings-row">
      <div>
        <b>关闭窗口后保留托盘</b>
        <p>从系统托盘打开物价补丁，或选择退出。</p>
      </div>
      <n-switch
        :value="app.settings.closeToTray"
        :disabled="app.running"
        aria-label="关闭窗口后保留托盘"
        @update:value="save({ closeToTray: $event })"
      />
    </div>
    <div class="settings-row">
      <div>
        <b>开机自动启动</b>
        <p>登录 Windows 后在托盘中启动。</p>
      </div>
      <n-switch
        :value="app.settings.autoStart"
        :disabled="app.running"
        aria-label="开机自动启动"
        @update:value="save({ autoStart: $event })"
      />
    </div>
    <div class="settings-row">
      <div>
        <b>每小时自动更新</b>
        <p>沿用最近一次成功更新的配置，每小时检查；仅手动关闭才停用。</p>
        <p>游戏运行、目录占用或本轮失败时，下个小时继续尝试。</p>
        <span v-if="app.settings.autoUpdate" class="schedule-note">{{
          app.state.nextUpdate
            ? `下次执行：${localeDate(app.state.nextUpdate)}`
            : '等待首次手动更新成功后开始计时。'
        }}</span>
      </div>
      <n-switch
        :value="app.settings.autoUpdate"
        aria-label="每小时自动更新"
        @update:value="save({ autoUpdate: $event })"
      />
    </div>
  </section>
  <section class="panel settings-panel">
    <div class="panel-heading">
      <h2>本地文件</h2>
      <Icon icon="ph:folder-open" />
    </div>
    <div class="settings-row">
      <div>
        <b>运行日志</b>
        <p>日志自动轮转，详细错误可用于排查问题。</p>
      </div>
      <n-button @click="attempt(() => desktop.openFolder('logs'))">打开文件夹</n-button>
    </div>
    <div class="settings-row">
      <div>
        <b>补丁输出与缓存</b>
        <p>游戏目录内的专属备份是还原依据，请妥善保留。</p>
      </div>
      <n-button @click="attempt(() => desktop.openFolder('output'))">查看输出</n-button>
    </div>
    <div class="settings-row">
      <div>
        <b>清理旧文件</b>
        <p>清理 7 天前的缓存与日志，保留最近文件、当前日志和游戏还原备份。</p>
      </div>
      <div class="cleanup-actions">
        <n-button :disabled="app.running || cleaning" :loading="cleaning" @click="cleanup('cache')"
          ><template #icon><Icon icon="ph:trash" /></template>清理旧缓存</n-button
        >
        <n-button :disabled="app.running || cleaning" @click="cleanup('logs')"
          ><template #icon><Icon icon="ph:trash" /></template>清理旧日志</n-button
        >
      </div>
    </div>
    <p v-if="cleanupResult" class="cleanup-result" role="status">{{ cleanupResult }}</p>
  </section>
  <section class="settings-panel open-source-section">
    <div class="panel-heading">
      <h2>本软件完全免费开源</h2>
      <Icon icon="ph:github-logo" />
    </div>
    <a
      href="https://github.com/weixiao030/poe2_price"
      @click.prevent="attempt(() => desktop.openCommunity('source'))"
      >https://github.com/weixiao030/poe2_price <Icon icon="ph:arrow-square-out"
    /></a>
    <a
      href="https://www.caimogu.cc/post/2403703.html"
      @click.prevent="attempt(() => desktop.openCommunity('community'))"
      >https://www.caimogu.cc/post/2403703.html <Icon icon="ph:arrow-square-out"
    /></a>
  </section>
  <p class="about-line">
    POE 物价补丁 v{{ app.state.version }} · 本地配置保存在当前 Windows 用户目录 · 禁止商业使用
  </p>
</template>
