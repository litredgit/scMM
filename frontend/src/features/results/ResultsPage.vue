<script setup lang="ts">
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
</script>

<template>
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 06 / 保存</p>
        <h1>结果与保存</h1>
        <p>保存当前项目，保留数据、预处理起点及已有只读报告。</p>
      </div>
      <span class="step-badge">06 / 06</span>
    </div>
    <div class="card">
      <div class="section-heading">
        <div>
          <h2>项目快照</h2>
          <p>{{ store.project.unsaved ? '当前工作区有未保存修改。' : '当前修改已保存。' }}</p>
        </div>
        <button
          class="primary"
          :disabled="store.busy"
          @click="store.mutate('/project/save', {}, 'POST', '项目快照已保存。')"
        >
          {{ store.busy ? '正在处理…' : '保存项目' }}
        </button>
      </div>
      <dl class="detail-list">
        <div>
          <dt>项目目录</dt>
          <dd>{{ store.project.path }}</dd>
        </div>
        <div>
          <dt>已保存修订</dt>
          <dd>r{{ store.project.manifest.revision }}</dd>
        </div>
        <div>
          <dt>当前数据</dt>
          <dd>
            {{
              store.project.dataset
                ? `${store.project.dataset.cells} 细胞 × ${store.project.dataset.features} 特征`
                : '尚未建立当前数据集'
            }}
          </dd>
        </div>
        <div v-if="store.project.manifest.artifacts">
          <dt>快照文件</dt>
          <dd>
            <pre>{{ JSON.stringify(store.project.manifest.artifacts, null, 2) }}</pre>
          </dd>
        </div>
      </dl>
      <p class="page-note">原始文件只引用。模型对象不保存，已有报告和图形重载后为只读记录。</p>
    </div>
    <div class="card">
      <h2>结果导出与管理</h2>
      <p class="muted">
        图表下载、独立 H5AD 导出和回收区将在后续阶段迁移。当前支持保存项目及重载已有快照。
      </p>
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>还没有打开项目</h1>
    <RouterLink to="/projects" class="button primary">前往项目首页 →</RouterLink>
  </div>
</template>
