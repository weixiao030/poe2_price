import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Root from './Root.vue'
import 'virtual:uno.css'
import './styles.css'
import './icons'

createApp(Root).use(createPinia()).mount('#app')
