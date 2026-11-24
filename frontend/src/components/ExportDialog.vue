<script setup lang="ts">
import { ref, useId } from 'vue'

defineProps<{ title: string }>()
defineEmits<{ close: [] }>()
const heading = useId()
const dialog = ref<HTMLDialogElement>()
defineExpose({
  open: () => {
    if (dialog.value && !dialog.value.open) dialog.value.showModal()
  },
  close: () => dialog.value?.close(),
})
</script>

<template>
  <dialog
    ref="dialog"
    class="export-dialog card"
    :aria-labelledby="heading"
    @close="$emit('close')"
  >
    <div class="export-heading">
      <h2 :id="heading">{{ title }}</h2>
      <button type="button" @click="dialog?.close()">关闭</button>
    </div>
    <div class="export-body"><slot /></div>
    <div class="export-footer actions"><slot name="footer" /></div>
  </dialog>
</template>

<style scoped>
.export-dialog {
  width: min(1240px, calc(100vw - 64px));
  max-height: min(900px, calc(100vh - 64px));
  color: var(--text, #223044);
  margin: auto;
  padding: 0;
  border-radius: 8px;
  box-shadow: 0 12px 48px #14233842;
}
.export-dialog[open] {
  display: flex;
  flex-direction: column;
}
.export-dialog::backdrop {
  background: #152d4866;
}
.export-heading {
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #dbe4ed;
}
.export-heading h2 {
  margin: 0;
}
.export-body {
  overflow: auto;
  padding: 12px 16px;
}
.export-footer {
  justify-content: end;
  padding: 10px 16px;
  border-top: 1px solid #dbe4ed;
}
</style>
