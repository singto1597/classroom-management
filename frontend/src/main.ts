import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/main.css'

import App from './App.vue'
import router from './router'
import { captureInstallPrompt, registerServiceWorker } from './services/pwa'

// 📲 ต้องฟัง `beforeinstallprompt` ที่ระดับโมดูล **ก่อน** Vue mount
// เพราะ event ยิงครั้งเดียวตอนโหลดหน้า — ฟังทีหลังจะพลาดไปแล้ว
captureInstallPrompt()

// ลงทะเบียน service worker (ภายในตรวจเองว่าเป็น production build หรือไม่)
void registerServiceWorker()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
