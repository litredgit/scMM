import { computed, onUnmounted, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { ionPath, type IonInfo } from '../../api/ions'
import { saveBlob, workspaceBlob } from '../../api/workspaceDownload'
import { useAnnotationSource } from '../annotation/useAnnotationSource'

export function useIonSource() {
  const { sourceId, source, grouping, selectTarget, selectedTarget } = useAnnotationSource()
  const store = useWorkspace()
  const info = ref<IonInfo>()
  const root = ref('')
  const version = ref('')
  let generation = 0
  const versions = computed(
    () => info.value?.versions?.filter((row) => row.root_id === root.value) ?? [],
  )
  async function refresh() {
    if (!store.project) {
      info.value = undefined
      return
    }
    const token = ++generation
    const result = await store.read<IonInfo>(ionPath('info'), undefined, () => token === generation)
    if (!result) return
    info.value = result
    root.value = result.roots?.some((row) => row.id === sourceId.value) ? sourceId.value : ''
    if (!versions.value.some((row) => row.id === version.value))
      version.value =
        versions.value.find((item) => item.id === grouping.value)?.id ??
        versions.value.at(-1)?.id ??
        ''
  }
  watch(
    () => [store.project?.path, store.current?.revision, sourceId.value],
    () => void refresh(),
    { immediate: true },
  )
  onUnmounted(() => {
    generation++
  })
  async function command(action: string, body: Record<string, unknown> = {}) {
    const result = await store.command(ionPath(action), body)
    if (result !== undefined) await refresh()
    return result
  }
  async function safely(action: () => Promise<unknown>) {
    try {
      await action()
    } catch (cause) {
      store.error = cause instanceof Error ? cause.message : String(cause)
    }
  }
  async function download(kind: string, key = '') {
    const snapshot = store.current
    if (!snapshot) return
    await store.run(
      async (scope) => {
        const query = new URLSearchParams({ kind, key, revision: String(snapshot.revision) })
        const blob = await workspaceBlob(`${ionPath('download')}?${query}`, {
          workspace: snapshot.workspace_id,
          isCurrent: () =>
            scope.isCurrent() &&
            store.current?.workspace_id === snapshot.workspace_id &&
            store.current?.revision === snapshot.revision,
        })
        saveBlob(
          blob,
          kind === 'bundle'
            ? 'ion-project.zip'
            : kind === 'source_l2'
              ? 'compound-source.h5ad'
              : 'ion-evidence.json',
        )
      },
      '',
      { label: '下载离子数据', phase: 'downloading' },
    )
  }
  return {
    store,
    info,
    root,
    source,
    version,
    versions,
    grouping,
    selectTarget,
    selectedTarget,
    refresh,
    command,
    safely,
    download,
  }
}

export function ids(text: string) {
  return text.split(/[\s,;]+/).filter(Boolean)
}

export function useIonPolarity() {
  const polarity = ref('pos'),
    ppm = ref(5)
  const species = ref(['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+', '[M+H-H2O]+'])
  watch(polarity, (value) => {
    species.value =
      value === 'pos'
        ? ['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+', '[M+H-H2O]+']
        : ['[M-H]-', '[M-2H]2-', '[2M-H]-']
  })
  return { polarity, ppm, species }
}
