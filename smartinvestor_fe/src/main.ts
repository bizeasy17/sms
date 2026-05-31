import { createApp } from 'vue'
import App from './App.vue'
import router from "./router"
import { createPinia } from 'pinia'
import 'element-plus/dist/index.css'

// import { ElHeader, ElContainer, ElAside, ElMain, ElText, ElRadioGroup, ElRadioButton, ElButton, ElLink, ElIcon,ElMenuItemGroup, ElCard,ElBadge, ElTag,
//      ElMenu, ElMenuItem, ElDivider, ElDialog, ElRow, ElCol, ElInput, ElDatePicker,   } from 'element-plus'

const app = createApp(App)
const pinia = createPinia()

// 全局注入 baseURL，优先读取环境变量 VITE_API_BASE_URL
const configuredApiBase = String(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5001/api').trim().replace(/\/+$/, '')
app.provide('baseURL', configuredApiBase)

app.use(pinia)
app.use(router).mount('#app')
