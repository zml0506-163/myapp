import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'

// 引入 Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

// 1. 导入路由配置（src/router/index.js）
import router from './router'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// 2. 挂载路由实例（关键补充：让 <router-view/> 能识别路由规则）
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')