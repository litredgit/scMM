<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useWorkspace } from './stores/workspace'

const store = useWorkspace()
onMounted(() => {
  void store.start()
  window.addEventListener('pagehide', store.release)
})
onUnmounted(() => window.removeEventListener('pagehide', store.release))
const pending = ['原始谱与参数', '提取与审核', '预处理', '分析']
</script>

<template>
  <div class="workbench">
    <aside class="sidebar">
      <RouterLink to="/projects" class="brand" aria-label="scMM 项目首页">
        <span class="brand-mark">s</span><span>scMM<small>单细胞质谱工作台</small></span>
      </RouterLink>
      <p class="nav-caption">实验工作流</p>
      <nav aria-label="工作流程">
        <RouterLink to="/projects"><span class="nav-number">⌂</span>项目首页</RouterLink>
        <RouterLink to="/samples"><span class="nav-number">1</span>项目与样本</RouterLink>
        <button
          v-for="(name, i) in pending"
          :key="name"
          disabled
          :title="`${name}将在后续迁移阶段开放`"
        >
          <span class="nav-number">{{ i + 2 }}</span
          >{{ name }}<small>待迁移</small>
        </button>
        <RouterLink to="/results"><span class="nav-number">6</span>结果与保存</RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <RouterLink to="/parameters">参数参考 <span>↗</span></RouterLink>
        <div class="connection">
          <i :class="{ connected: store.current }"></i
          >{{ store.current ? '工作区已连接' : '工作区未连接' }}
        </div>
        <p>项目与样本迁移阶段<br />保留六步实验流程</p>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <div class="project-heading">
          <span class="eyebrow">当前项目</span
          ><strong>{{ store.project?.manifest.name ?? '尚未打开项目' }}</strong>
        </div>
        <div class="topbar-actions">
          <span v-if="store.project" class="save-state" :class="{ dirty: store.project.unsaved }">{{
            store.project.unsaved ? '有未保存修改' : '已保存'
          }}</span>
          <button
            v-if="store.project"
            class="primary"
            :disabled="store.busy"
            @click="store.mutate('/project/save', {}, 'POST', '项目已保存。')"
          >
            {{ store.busy ? '正在处理…' : '保存项目' }}
          </button>
          <button
            v-if="store.project"
            :disabled="store.busy"
            @click="store.mutate('/project/close')"
          >
            关闭项目
          </button>
        </div>
      </header>
      <main id="main-content" :aria-busy="store.busy">
        <div v-if="store.error" role="alert" class="alert error">
          <span>{{ store.error }}</span>
          <div class="actions">
            <button v-if="store.current" @click="store.refresh()" :disabled="store.busy">
              刷新状态</button
            ><button @click="store.error = ''" aria-label="清除错误">×</button>
          </div>
        </div>
        <div v-if="store.notice" role="status" class="alert success">{{ store.notice }}</div>
        <div v-if="!store.current" class="card empty-state">
          <h1>连接实验工作区</h1>
          <p>服务重启或页面刷新后，请重新打开已保存的项目。</p>
          <button class="primary" :disabled="store.busy" @click="store.start()">
            {{ store.busy ? '正在连接…' : '重新连接' }}
          </button>
        </div>
        <RouterView v-else v-slot="{ Component }"
          ><KeepAlive><component :is="Component" /></KeepAlive
        ></RouterView>
      </main>
      <footer>scMM · CyESI 单细胞质谱分析<span>离开或刷新前请主动保存项目</span></footer>
    </div>
  </div>
</template>
