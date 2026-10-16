<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '../stores/auth'
const auth = useAuth()
const username = ref('')
const password = ref('')
const newPassword = ref('')
const repeat = ref('')
async function submit() {
  if (auth.user?.must_change) {
    if (newPassword.value !== repeat.value) {
      auth.error = '两次输入的新密码不一致。'
      return
    }
    if (await auth.changePassword('', newPassword.value)) {
      newPassword.value = ''
      repeat.value = ''
    }
  } else {
    await auth.login(username.value, password.value)
    password.value = ''
  }
}
</script>
<template>
  <main class="login-shell">
    <form class="card login-card" @submit.prevent="submit">
      <h1>scMM 工作台</h1>
      <p>
        {{
          auth.user?.must_change
            ? '首次登录或密码重置后，请设置自己的密码。'
            : '使用管理员为你创建的账号登录。团队共享项目和原始数据。'
        }}
      </p>
      <p v-if="auth.error" class="alert error" role="alert">{{ auth.error }}</p>
      <template v-if="!auth.user?.must_change">
        <label
          >账号<input v-model="username" autocomplete="username" required maxlength="64"
        /></label>
        <label
          >密码<input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            maxlength="128"
        /></label>
      </template>
      <template v-else>
        <label
          >新密码<input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            required
            minlength="15"
            maxlength="128"
        /></label>
        <label
          >再次输入新密码<input
            v-model="repeat"
            type="password"
            autocomplete="new-password"
            required
            minlength="15"
            maxlength="128"
        /></label>
        <p class="muted">15–128 个字符。修改后所有设备需要重新登录。</p>
      </template>
      <button class="primary" :disabled="auth.busy">
        {{ auth.busy ? '正在处理…' : auth.user?.must_change ? '设置密码' : '登录' }}
      </button>
    </form>
  </main>
</template>
<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1rem;
}
.login-card {
  width: min(100%, 28rem);
}
label {
  display: grid;
  gap: 0.5rem;
  margin: 1rem 0;
}
</style>
