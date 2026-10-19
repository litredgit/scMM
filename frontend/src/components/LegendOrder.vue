<script setup lang="ts">
import { ref } from 'vue'
import { legendLabel } from './useLegendOrder'
defineProps<{ items: string[]; disabled?: boolean }>()
const emit = defineEmits<{ move: [from: number, to: number]; reset: [] }>()
const dragged = ref<number>()
function drop(index: number) {
  if (dragged.value !== undefined) emit('move', dragged.value, index)
  dragged.value = undefined
}
</script>
<template>
  <details v-if="items.length > 1" class="legend-order">
    <summary>调整图例顺序（默认名称升序）</summary>
    <p class="muted">拖动或用上下按钮调整，顺序随项目保存，颜色保持对应。</p>
    <ol>
      <li
        v-for="(item, i) in items"
        :key="item"
        :draggable="!disabled"
        @dragstart="dragged = i"
        @dragend="dragged = undefined"
        @dragover.prevent
        @drop.prevent="!disabled && drop(i)"
      >
        <span>{{ legendLabel(item) }}</span>
        <button
          class="secondary"
          :aria-label="`上移图例 ${legendLabel(item)}`"
          :disabled="disabled || i === 0"
          @click="emit('move', i, i - 1)"
        >
          ↑
        </button>
        <button
          class="secondary"
          :aria-label="`下移图例 ${legendLabel(item)}`"
          :disabled="disabled || i === items.length - 1"
          @click="emit('move', i, i + 1)"
        >
          ↓
        </button>
      </li>
    </ol>
    <button class="restore" :disabled="disabled" @click="emit('reset')">恢复图例默认顺序</button>
  </details>
</template>
<style scoped>
.legend-order {
  margin: 12px 0;
}
ol {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0;
  list-style: none;
}
li {
  display: flex;
  gap: 6px;
  align-items: center;
  background: #f5f7fb;
  padding: 6px 10px;
  border-radius: 8px;
  max-width: 100%;
}
li span {
  overflow-wrap: anywhere;
}
li button {
  min-height: 30px;
  padding: 2px 8px;
}
</style>
