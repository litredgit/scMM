<script setup lang="ts">
defineProps<{
  samples: {
    id: string
    name: string
    parameter_source: string
    parameters: { mz_min: number; mz_max: number; ref_mz: number }
  }[]
}>()
</script>

<template>
  <details>
    <summary>样本参数（{{ samples.length }} 个）</summary>
    <table>
      <thead>
        <tr>
          <th>样本</th>
          <th>参数来源</th>
          <th>提取范围 (m/z)</th>
          <th>参考离子 (m/z)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in samples" :key="row.id">
          <td>{{ row.name }}</td>
          <td>{{ row.parameter_source === 'sample' ? '样本' : '项目' }}</td>
          <td>{{ row.parameters.mz_min }}–{{ row.parameters.mz_max }}</td>
          <td>{{ row.parameters.ref_mz }}</td>
        </tr>
      </tbody>
    </table>
  </details>
</template>
