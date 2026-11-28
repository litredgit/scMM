<script setup lang="ts">
import { ref, useId, onBeforeUnmount, onDeactivated, nextTick } from 'vue'
const props = defineProps<{ text: string; label?: string }>()
const id = useId()
const visible = ref(false)
const anchor = ref<HTMLElement>()
const bubble = ref<HTMLElement>()
let hideTimer: ReturnType<typeof setTimeout> | undefined
let clicked = false
const location = ref({ left: '0px', top: '0px', maxWidth: '360px' })
function show() {
  clearTimeout(hideTimer)
  if (!props.text || !anchor.value) return
  const box = anchor.value.getBoundingClientRect()
  const width = Math.min(380, window.innerWidth - 24)
  location.value = {
    left: `${Math.max(12, Math.min(box.left, window.innerWidth - width - 12))}px`,
    top: `${box.bottom + 8}px`,
    maxWidth: `${width}px`,
  }
  if (!visible.value) {
    window.addEventListener('scroll', follow, true)
    window.addEventListener('resize', follow)
    visible.value = true
  }
  void nextTick(() => {
    const height = bubble.value?.getBoundingClientRect().height ?? 0
    if (height && box.bottom + 8 + height > window.innerHeight - 12)
      location.value.top = `${Math.max(12, box.top - height - 8)}px`
  })
}
function later() {
  hideTimer = setTimeout(hide, 150)
}
function hide() {
  clearTimeout(hideTimer)
  visible.value = false
  clicked = false
  window.removeEventListener('scroll', follow, true)
  window.removeEventListener('resize', follow)
}
function follow() {
  if (visible.value) show()
}
function toggle() {
  if (clicked) hide()
  else {
    show()
    clicked = visible.value
  }
}
onBeforeUnmount(hide)
onDeactivated(hide)
</script>
<template>
  <span v-if="text" class="help-tip" @mouseenter="show" @mouseleave="later">
    <button
      ref="anchor"
      type="button"
      class="help-trigger"
      :aria-label="`${label ?? ''}说明`"
      :aria-describedby="visible ? id : undefined"
      @focus="show"
      @blur="hide"
      @keydown.esc="hide"
      @click.stop.prevent="toggle"
    >
      <span aria-hidden="true">?</span>
    </button>
    <Teleport to="body"
      ><div
        v-if="visible"
        ref="bubble"
        @mouseenter="show"
        @mouseleave="later"
        :id="id"
        role="tooltip"
        class="help-popover"
        :style="location"
      >
        {{ text }}
      </div></Teleport
    >
  </span>
</template>
