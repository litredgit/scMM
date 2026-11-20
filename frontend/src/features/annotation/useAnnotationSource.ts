import { computed, shallowRef } from 'vue'
import { useWorkspace } from '../../stores/workspace'

const choice = shallowRef<{ project: string; id: string }>()
const groupingChoice = shallowRef<{ project: string; source: string; version: string }>()
export type ReviewTarget = {
  source: string
  sourceIdentity: string
  kind: 'feature' | 'candidate' | 'ec'
  id: string
  featureId?: string
  version?: string
  mz?: number
  members?: string[]
  quantifier?: string
}
const target = shallowRef<{ project: string; value: ReviewTarget }>()

export function useAnnotationSource() {
  const store = useWorkspace()
  const project = computed(() => `${store.current?.workspace_id}:${store.project?.path}`)
  const sources = computed(() => store.project?.annotation?.sources ?? [])
  const source = computed(() => {
    const selected = choice.value?.project === project.value ? choice.value?.id : undefined
    return (
      sources.value.find((entry) => entry.id === selected) ??
      sources.value.find((entry) => entry.id === store.project?.annotation?.default_source)
    )
  })
  const sourceId = computed({
    get: () => source.value?.id ?? '',
    set: (id: string) => {
      if (sources.value.some((entry) => entry.id === id))
        choice.value = { project: project.value, id }
    },
  })
  const selectedTarget = computed(() =>
    target.value?.project === project.value &&
    target.value.value.source === source.value?.id &&
    target.value.value.sourceIdentity === source.value?.identity
      ? target.value.value
      : undefined,
  )
  const grouping = computed({
    get: () =>
      groupingChoice.value?.project === project.value &&
      groupingChoice.value.source === sourceId.value
        ? groupingChoice.value.version
        : '',
    set: (version: string) => {
      groupingChoice.value = { project: project.value, source: sourceId.value, version }
    },
  })
  return {
    source,
    sourceId,
    sources,
    grouping,
    selectedTarget,
    clearTarget: () => {
      target.value = undefined
    },
    selectTarget: (value: ReviewTarget) => {
      target.value = { project: project.value, value }
    },
  }
}
