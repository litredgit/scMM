import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './styles.css'
import HelpTip from './components/HelpTip.vue'
import FieldLabel from './components/FieldLabel.vue'

createApp(App)
  .component('HelpTip', HelpTip)
  .component('FieldLabel', FieldLabel)
  .use(createPinia())
  .use(router)
  .mount('#app')
