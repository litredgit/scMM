<script setup lang="ts">
import { computed } from 'vue'
import { displayName } from '../../../help/labels'
export interface Scope {
  group_key: string
  groups: string[] | null
  sample_key: string
  samples: string[] | null
}
const props = defineProps<{
  modelValue: Scope
  observations: Record<string, string[]>
  disabled?: boolean
  ordered?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Scope] }>()
const groupOptions = computed(() => props.observations[props.modelValue.group_key] ?? [])
const sampleOptions = computed(() => props.observations[props.modelValue.sample_key] ?? [])
const chosenSamples = computed(() => props.modelValue.samples ?? sampleOptions.value)
function update(value: Partial<Scope>) {
  emit('update:modelValue', { ...props.modelValue, ...value })
}
function toggle(field: 'groups' | 'samples', name: string, options: string[]) {
  const current = props.modelValue[field] ?? options
  update({
    [field]: current.includes(name) ? current.filter((v) => v !== name) : [...current, name],
  })
}
function move(index: number, step: number) {
  const values = [...chosenSamples.value]
  const target = index + step
  if (target < 0 || target >= values.length) return
  ;[values[index], values[target]] = [values[target]!, values[index]!]
  update({ samples: values })
}
</script>
<template>
  <fieldset :disabled="disabled" class="plot-scope">
    <legend>作图范围</legend>
    <p class="muted">
      只筛选图形与作图数据，不裁剪当前矩阵，不重新运行统计或降维。修改后点击绘图按钮生效。
    </p>
    <div class="field-grid">
      <label
        >筛选分组列<select
          :value="modelValue.group_key"
          aria-label="作图分组列"
          @change="update({ group_key: ($event.target as HTMLSelectElement).value, groups: null })"
        >
          <option v-if="!observations[modelValue.group_key]" :value="modelValue.group_key">
            {{ displayName(modelValue.group_key) }}（不可用）
          </option>
          <option v-for="(_, key) in observations" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      >
      <label
        >筛选样本列<select
          :value="modelValue.sample_key"
          aria-label="作图样本列"
          @change="
            update({ sample_key: ($event.target as HTMLSelectElement).value, samples: null })
          "
        >
          <option v-if="!observations[modelValue.sample_key]" :value="modelValue.sample_key">
            {{ displayName(modelValue.sample_key) }}（不可用）
          </option>
          <option v-for="(_, key) in observations" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      >
    </div>
    <details>
      <summary>
        组别 · {{ modelValue.groups === null ? '全部' : `已选 ${modelValue.groups.length}` }}
      </summary>
      <div class="actions">
        <button type="button" @click="update({ groups: null })">全部组别</button
        ><button type="button" @click="update({ groups: [] })">清空组别</button>
      </div>
      <label v-for="name in groupOptions" :key="name" class="inline-check"
        ><input
          type="checkbox"
          :aria-label="`作图组别 ${name}`"
          :checked="modelValue.groups === null || modelValue.groups.includes(name)"
          @change="toggle('groups', name, groupOptions)"
        />{{ name }}</label
      >
    </details>
    <details>
      <summary>
        样本 · {{ modelValue.samples === null ? '全部' : `已选 ${modelValue.samples.length}` }}
      </summary>
      <div class="actions">
        <button type="button" @click="update({ samples: null })">全部样本</button
        ><button type="button" @click="update({ samples: [] })">清空样本</button>
      </div>
      <label v-for="name in sampleOptions" :key="name" class="inline-check"
        ><input
          type="checkbox"
          :aria-label="`作图样本 ${name}`"
          :checked="chosenSamples.includes(name)"
          @change="toggle('samples', name, sampleOptions)"
        />{{ name }}</label
      >
      <ol v-if="ordered && chosenSamples.length">
        <li v-for="(name, i) in chosenSamples" :key="name">
          {{ name }}
          <button
            type="button"
            :aria-label="`${name} 上移`"
            :disabled="disabled || i === 0"
            @click="move(i, -1)"
          >
            上移
          </button>
          <button
            type="button"
            :aria-label="`${name} 下移`"
            :disabled="disabled || i === chosenSamples.length - 1"
            @click="move(i, 1)"
          >
            下移
          </button>
        </li>
      </ol>
    </details>
    <p v-if="modelValue.groups?.length === 0 || modelValue.samples?.length === 0" role="status">
      范围为空，请至少选择一个组别和样本。
    </p>
  </fieldset>
</template>
<style scoped>
.plot-scope {
  min-width: 0;
  border: 1px solid #d8e0eb;
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
}
.plot-scope label,
.plot-scope li {
  overflow-wrap: anywhere;
}
.plot-scope li {
  margin: 6px 0;
}
</style>
