<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  darkTheme,
  zhCN,
  dateZhCN,
  NConfigProvider,
  NDialogProvider,
  NMessageProvider
} from 'naive-ui'
import { useAppStore } from './stores/app'
import App from './App.vue'
const store = useAppStore()
const media = window.matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(media.matches)
const changed = () => {
  systemDark.value = media.matches
}
onMounted(() => media.addEventListener('change', changed))
onUnmounted(() => media.removeEventListener('change', changed))
const isDark = computed(
  () => store.settings.theme === 'dark' || (store.settings.theme === 'system' && systemDark.value)
)
const overrides = computed(() => ({
  common: {
    fontFamily: '"Segoe UI", "Microsoft YaHei UI", sans-serif',
    primaryColor: isDark.value ? '#72c6a9' : '#176b55',
    primaryColorHover: isDark.value ? '#8dd9bf' : '#228168',
    primaryColorPressed: '#125440',
    borderRadius: '7px',
    fontSize: '13px'
  }
}))
</script>
<template>
  <n-config-provider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme="isDark ? darkTheme : null"
    :theme-overrides="overrides"
    :class="['theme-root', { dark: isDark, 'custom-background': !!store.background }]"
    :style="{
      '--background-image': store.background ? `url(${store.background})` : 'none',
      '--background-opacity': store.settings.backgroundOpacity / 100
    }"
  >
    <n-message-provider
      ><n-dialog-provider><App /></n-dialog-provider
    ></n-message-provider>
  </n-config-provider>
</template>
