<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useReadScope } from '../../api/readScope'
import { useWorkspace } from '../../stores/workspace'

type MassList = {
  id: string
  name: string
  count: number
  origin: { type: string; adducts?: string[] }
}

const props = defineProps<{ active: boolean }>()
const pending = defineModel<boolean>('pending', { default: false })
const store = useWorkspace()
const strategy = ref('shared')
const listId = ref('')
const lists = ref<MassList[]>([])
const selected = computed(() => lists.value.find((item) => item.id === listId.value))
const file = ref<File>()
const fileInput = ref<HTMLInputElement>()
const name = ref('')
const listPreview = ref<number[]>()
const massPage = ref(0)
const context = () => [store.current?.workspace_id, store.project?.path]
const reads = useReadScope(context, () => void refresh())
const listReads = useReadScope(() => [context(), listId.value])

async function refresh() {
  const accept = reads.begin()
  const values = await store.read<MassList[]>('/extraction/lists', undefined, accept)
  if (accept() && values) lists.value = values
}

watch(
  () =>
    JSON.stringify([
      ...context(),
      store.project?.manifest.feature_strategy,
      store.project?.manifest.feature_list_id,
    ]),
  () => {
    strategy.value = store.project?.manifest.feature_strategy ?? 'shared'
    listId.value = String(store.project?.manifest.feature_list_id ?? '')
    if (store.project) void refresh()
  },
  { immediate: true },
)
watch(
  () => store.current?.revision,
  () => void refresh(),
)
watch(listId, () => {
  listPreview.value = undefined
  massPage.value = 0
})

async function viewList() {
  const accept = listReads.begin()
  const query = new URLSearchParams({ list_id: listId.value })
  const result = await store.read<{ mz: number[] }>(`/extraction/lists?${query}`, undefined, accept)
  if (accept() && result) listPreview.value = result.mz
}

async function upload() {
  const source = file.value
  if (!source) return
  const original = JSON.stringify(context())
  const content = await source.text()
  if (original !== JSON.stringify(context())) return
  const result = await store.command<MassList>('/extraction/lists', {
    filename: source.name,
    name: name.value,
    content,
  })
  if (!result || original !== JSON.stringify(context())) return
  if (!lists.value.some((item) => item.id === result.id)) lists.value.push(result)
  strategy.value = 'list'
  listId.value = result.id
  file.value = undefined
  if (fileInput.value) fileInput.value.value = ''
  name.value = ''
}

async function apply() {
  await store.mutate(
    '/extraction/feature-source',
    { strategy: strategy.value, list_id: strategy.value === 'list' ? listId.value : null },
    'PUT',
    '特征来源已应用。',
  )
}

const edited = computed(
  () =>
    strategy.value !== store.project?.manifest.feature_strategy ||
    (strategy.value === 'list' && listId.value !== store.project?.manifest.feature_list_id),
)
watch(
  edited,
  (value) => {
    pending.value = value
  },
  { immediate: true },
)
</script>

<template>
  <div class="feature-source">
    <div class="actions">
      <label>
        特征来源
        <select v-model="strategy" aria-label="特征来源" :disabled="store.busy || props.active">
          <option value="shared">全项目叠加谱寻峰</option>
          <option value="independent">各样本独立寻峰后合并</option>
          <option value="list">固定 m/z 清单</option>
        </select>
      </label>
      <label v-if="strategy === 'list'">
        m/z 清单
        <select v-model="listId" aria-label="m/z 清单" :disabled="store.busy || props.active">
          <option value="" disabled>选择清单</option>
          <option v-for="item in lists" :key="item.id" :value="item.id">
            {{ item.name }} · {{ item.count }} 项
          </option>
        </select>
      </label>
      <button
        type="button"
        class="primary"
        :disabled="store.busy || props.active || !edited || (strategy === 'list' && !selected)"
        @click="apply"
      >
        应用特征来源
      </button>
      <button
        v-if="strategy === 'list' && selected"
        type="button"
        class="preview"
        :disabled="store.busy"
        @click="listPreview ? (listPreview = undefined) : viewList()"
      >
        {{ listPreview ? '收起清单' : '查看清单' }}
      </button>
    </div>
    <p v-if="edited" class="muted">当前选择待应用。</p>
    <p v-if="strategy === 'list' && selected?.origin.adducts?.length" class="muted">
      参考加合物 {{ selected.origin.adducts.join('、') }}
    </p>
    <div v-if="listPreview" class="feature-list-preview">
      <div class="actions">
        <button :disabled="massPage === 0" @click="massPage--">上一页</button>
        <span
          >{{ massPage * 40 + 1 }}–{{ Math.min((massPage + 1) * 40, listPreview.length) }} /
          {{ listPreview.length }}</span
        >
        <button :disabled="(massPage + 1) * 40 >= listPreview.length" @click="massPage++">
          下一页
        </button>
      </div>
      <div class="mass-values">
        <code v-for="mz in listPreview.slice(massPage * 40, (massPage + 1) * 40)" :key="mz">{{
          mz
        }}</code>
      </div>
    </div>
    <details>
      <summary>上传 m/z 清单</summary>
      <div class="actions">
        <label
          >文件<input
            ref="fileInput"
            type="file"
            accept=".csv,.tsv,.txt"
            :disabled="store.busy || props.active"
            @change="file = ($event.target as HTMLInputElement).files?.[0]"
        /></label>
        <label>清单名称<input v-model="name" maxlength="100" placeholder="默认使用文件名" /></label>
        <button
          type="button"
          class="save"
          :disabled="store.busy || props.active || !file || file.size > 2_000_000"
          @click="upload"
        >
          导入清单
        </button>
      </div>
      <p class="muted" v-if="file && file.size > 2_000_000">请选择不超过 2 MB 的文本文件。</p>
      <p class="muted" v-else>
        每行一个 m/z，或带 mz / m/z 表头的 CSV、TSV。保存项目后可再次选用。
      </p>
    </details>
  </div>
</template>

<style scoped>
.feature-source {
  display: grid;
  gap: 8px;
  margin-block: 8px 12px;
}
.feature-source .actions {
  align-items: end;
}
.feature-source p {
  margin: 0;
}
.feature-source details > .actions {
  margin-top: 8px;
}
.mass-values {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 8px;
}
</style>
