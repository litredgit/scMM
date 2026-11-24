<script setup lang="ts">
import { colorScales, palettes, defaultPlotColors } from './plotColors'
defineProps<{ continuous: boolean }>()
const model = defineModel<typeof defaultPlotColors>({ required: true })
</script>

<template>
  <template v-if="continuous">
    <label
      >连续色标
      <select v-model="model.colorscale">
        <option v-for="scale in colorScales" :key="scale">{{ scale }}</option>
      </select>
    </label>
    <label
      >颜色数值变换
      <select v-model="model.transform">
        <option value="linear">原值</option>
        <option value="log1p">log1p（非负值）</option>
        <option value="symlog">对称对数</option>
      </select>
    </label>
    <label v-if="model.transform === 'symlog'"
      >对称对数参考尺度
      <input v-model.number="model.linthresh" type="number" min="1e-12" step="any" />
    </label>
  </template>
  <label v-else
    >分类配色
    <select v-model="model.palette">
      <option v-for="palette in palettes" :key="palette">{{ palette }}</option>
    </select>
  </label>
</template>
