<script setup lang="ts">
import { nextTick } from 'vue'
defineProps<{ items: { id: string; label: string; available?: boolean }[] }>()
async function go(id: string) {
  const target = document.getElementById(id)
  if (!target) return
  target
    .querySelector<HTMLButtonElement>('.calculation-heading button[aria-expanded="false"]')
    ?.click()
  await nextTick()
  const header = document.querySelector('.topbar')?.getBoundingClientRect().height ?? 0
  window.scrollTo({ top: Math.max(0, scrollY + target.getBoundingClientRect().top - header - 12) })
}
</script>
<template>
  <nav class="section-nav actions" aria-label="本页分区">
    <button
      v-for="item in items"
      :key="item.id"
      :disabled="item.available === false"
      :title="item.available === false ? '请先生成或读取有效结果。' : undefined"
      @click="go(item.id)"
    >
      {{ item.label }}
    </button>
  </nav>
</template>
