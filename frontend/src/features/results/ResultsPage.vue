<script setup lang="ts">
import { displayName } from '../../help/labels'
import { ref, watch, computed, onActivated } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import type { AnalysisInfo, Figure } from '../../api/types'
import { resultDownloads } from '../analysis/results'
import SavedItems from '../../components/SavedItems.vue'
import PlotView from '../../components/PlotView.vue'
const store = useWorkspace(),
  info = ref<AnalysisInfo>()
const root = ref('项目结果'),
  directory = ref('.'),
  filename = ref(''),
  downloadName = ref(''),
  embedding = ref(''),
  kind = ref('matrix'),
  exported = ref('')
watch(root, (value) => {
  directory.value =
    value === '项目结果' && store.project ? `${store.project.path.split('/').at(-1)}/exports` : '.'
})
const figureKey = ref(''),
  figure = ref<Figure>()
const artifactRefs = computed(
  () => store.project?.manifest.artifacts as Record<string, string> | undefined,
)
const defaults: Record<string, string> = {
  matrix: 'matrix.csv',
  embedding: 'embedding.csv',
  qc: 'cell_qc.csv',
  history: 'history.csv',
  ...resultDownloads,
  snapshot: 'snapshot.h5ad',
}
const available = computed(() => [
  { value: 'matrix', label: '当前矩阵 CSV' },
  { value: 'embedding', label: '嵌入坐标 CSV' },
  { value: 'qc', label: '细胞 QC CSV' },
  { value: 'history', label: '处理记录 CSV' },
  ...(info.value?.results ?? [])
    .filter((n) => n in defaults)
    .map((n) => ({ value: n, label: `${n} ${n === 'supervised' ? 'JSON' : 'CSV'}` })),
  { value: 'snapshot', label: '上次保存快照 H5AD' },
])
let generation = 0
async function refresh() {
  const token = ++generation
  info.value = undefined
  figure.value = undefined
  exported.value = ''
  if (!store.project) return
  root.value = '项目结果'
  directory.value = `${store.project.path.split('/').at(-1)}/exports`
  const time = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
    .format(new Date())
    .replace(/[-: ]/g, '')
  filename.value = `${store.project.manifest.name.replace(/[^\p{L}\p{N}_-]/gu, '_')}_${time}.h5ad`
  if (store.project.dataset) {
    const value = await store.read<AnalysisInfo>('/analysis')
    if (token !== generation) return
    info.value = value
    embedding.value = value?.embeddings[0] ?? ''
    figureKey.value = value?.figures[0] ?? ''
  }
}
watch(
  [
    () => store.project?.path,
    () => store.project?.dataset?.id,
    () => store.project?.dataset?.revision,
  ],
  () => void refresh(),
  { immediate: true },
)
async function showFigure() {
  if (figureKey.value)
    figure.value = await store.read<Figure>(
      `/analysis/figures/${encodeURIComponent(figureKey.value)}`,
    )
}
watch(kind, () => (downloadName.value = defaults[kind.value] ?? 'result.csv'), { immediate: true })
onActivated(() => void refresh())
async function exportH5ad() {
  const result = await store.command<{ path: string }>('/results/export', {
    root: root.value,
    directory: directory.value,
    filename: filename.value,
  })
  if (result) {
    exported.value = result.path
    store.notice = '当前数据已单独导出。项目快照仍由“保存项目”更新。'
  }
}
</script>
<template>
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 06 / 保存</p>
        <h1>结果与保存</h1>
        <p>主动保存当前项目，导出完整数据和可追溯报告。</p>
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
          class="save"
          :disabled="store.busy"
          @click="store.mutate('/project/save', {}, 'POST', '项目快照已保存。')"
        >
          保存项目
        </button>
      </div>
      <p class="muted">保存项目用于继续完整工作；下载到本机与服务器独立导出不替代保存。</p>
    </div>
    <div v-if="store.project.dataset" class="card">
      <h2>下载与独立导出</h2>
      <div class="result-export-grid">
        <section aria-label="下载到本机">
          <h3>下载到本机</h3>
          <div class="field-grid">
            <label
              ><FieldLabel name="下载内容" /><select
                aria-label="下载内容"
                v-model="kind"
                :disabled="store.busy"
              >
                <option v-for="v in available" :key="v.value" :value="v.value">
                  {{ v.label }}
                </option>
              </select></label
            ><label v-if="kind === 'embedding'"
              ><FieldLabel name="嵌入键" /><select
                aria-label="嵌入键"
                v-model="embedding"
                :disabled="store.busy"
              >
                <option v-for="v in info?.embeddings" :key="v" :value="v">
                  {{ displayName(v) }}
                </option>
              </select></label
            ><label
              ><FieldLabel name="下载文件名" /><input
                aria-label="下载文件名"
                v-model="downloadName"
                :disabled="store.busy"
            /></label>
          </div>
          <button
            class="save"
            :disabled="store.busy || (kind === 'embedding' && !embedding)"
            @click="store.download(kind, downloadName, kind === 'embedding' ? embedding : '')"
          >
            下载完整结果
          </button>
          <p class="muted">
            显示格式不降低 CSV
            精度。失效结果不可下载。重载的监督报告只读，SHAP/潜变量需重新训练模型。
          </p>
        </section>
        <section aria-label="导出到服务器">
          <h3>单独导出当前 H5AD</h3>
          <div class="field-grid">
            <label
              ><FieldLabel name="保存存储" /><select
                aria-label="保存存储"
                v-model="root"
                :disabled="store.busy"
              >
                <option v-for="r in store.configuration?.results" :key="r.label">
                  {{ r.label }}
                </option>
              </select></label
            ><label
              ><FieldLabel name="保存目录" /><input
                aria-label="保存目录"
                v-model="directory"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="H5AD 文件名" /><input
                aria-label="H5AD 文件名"
                v-model="filename"
                :disabled="store.busy"
            /></label>
          </div>
          <p class="path">
            目标：{{ store.configuration?.results.find((r) => r.label === root)?.path }} /
            {{ directory }} / {{ filename }}
          </p>
          <button class="save" :disabled="store.busy || !filename" @click="exportH5ad">
            导出当前 H5AD（不覆盖）
          </button>
          <p v-if="exported" role="status">已导出：{{ exported }}</p>
          <p class="page-note">
            独立 H5AD
            保留当前轴上的历史层、嵌入和报告；完整恢复起点由项目快照保存。导出不替代保存项目。
          </p>
        </section>
      </div>
      <template v-if="info?.figures.length">
        <h3>项目图形</h3>
        <div class="field-grid">
          <label
            ><FieldLabel name="已保存图形" /><select
              aria-label="已保存图形"
              v-model="figureKey"
              :disabled="store.busy"
              @change="figure = undefined"
            >
              <option v-for="key in info.figures" :key="key">{{ key }}</option>
            </select></label
          >
        </div>
        <div class="actions">
          <button class="preview" :disabled="store.busy || !figureKey" @click="showFigure">
            查看图形</button
          ><button
            class="save"
            :disabled="store.busy || !figureKey"
            @click="store.download('figure', `${figureKey}.json`, figureKey)"
          >
            下载图形 JSON
          </button>
        </div>
        <PlotView v-if="figure" :figure="figure" :name="figureKey" />
      </template>
    </div>
    <details class="card">
      <summary>项目快照详情</summary>
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
        <template v-if="store.project.manifest.artifacts">
          <div
            v-for="(label, key) in {
              current: '当前已保存结果',
              baseline: '完整恢复起点',
              views: '图形与视图设置',
            }"
            :key="key"
          >
            <dt>{{ label }}</dt>
            <dd>
              {{ artifactRefs?.[key]?.split('/').at(-1) || '暂无' }}
              <HelpTip
                :label="label"
                :text="`${store.project.path}/${artifactRefs?.[key] ?? ''}`"
              />
            </dd>
          </div>
        </template>
      </dl>
      <p class="page-note">
        快照包含当前数据、完整预处理起点及只读报告和图形。原始文件只引用；可执行模型不序列化。
      </p>
    </details>
    <details class="card">
      <summary>H5AD 保留与管理</summary>
      <p>
        保存项目会写入当前数据和完整恢复起点；重复保存保留旧快照。提取和细胞预览也会产生
        H5AD，独立导出则产生一份单独矩阵。
      </p>
      <p class="page-note">
        完整继续分析请打开项目；导入 H5AD
        只读取所选矩阵。内部文件默认收起，当前引用和活动任务产物受保护；旧快照按删除计划手动移入回收区，回收区清空后才释放空间。
      </p>
    </details>
  </section>
  <div v-else class="card empty-state">
    <h1>还没有打开项目</h1>
    <RouterLink to="/projects" class="button primary">前往项目首页 →</RouterLink>
  </div>
  <SavedItems />
</template>
