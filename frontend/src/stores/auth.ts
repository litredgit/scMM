import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { request, setSession } from '../api/client'

export type User = {
  id: string
  username: string
  role: string
  must_change: boolean
  csrf: string
}

export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)
  const error = ref('')
  const busy = ref(false)
  const admin = computed(() => user.value?.role === 'admin')
  window.addEventListener('scmm-auth-expired', () => {
    user.value = null
    error.value = '登录已失效，请重新登录；未保存工作区仍受原有效期限制。'
  })
  async function refresh() {
    try {
      user.value = await request<User>('/auth/me')
      setSession(user.value.csrf)
      error.value = ''
    } catch {
      user.value = null
    } finally {
      ready.value = true
    }
  }
  async function login(username: string, password: string) {
    busy.value = true
    error.value = ''
    try {
      setSession('')
      user.value = await request<User>('/auth/login', {
        method: 'POST',
        body: { username, password },
      })
      setSession(user.value.csrf)
      return true
    } catch (cause) {
      error.value = String(cause instanceof Error ? cause.message : cause)
      return false
    } finally {
      busy.value = false
    }
  }
  async function changePassword(current_password: string, new_password: string) {
    busy.value = true
    error.value = ''
    try {
      await request('/auth/password', { method: 'POST', body: { current_password, new_password } })
      setSession('')
      user.value = null
      error.value = '密码已更新，请使用新密码登录。'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      busy.value = false
    }
  }
  async function logout() {
    await request('/auth/logout', { method: 'POST' })
    setSession('')
    user.value = null
  }
  return { user, ready, admin, error, busy, refresh, login, changePassword, logout }
})
