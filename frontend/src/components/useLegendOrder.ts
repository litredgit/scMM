import { computed, ref, type ComputedRef } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { useViewState } from '../api/viewState'
export function legendLabel(name: string) {
  return /^[/\\]|^[a-z]:[/\\]/i.test(name)
    ? name.replace(/\\/g, '/').split('/').at(-1) || name
    : name
}
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
export function useLegendOrder(
  key: ComputedRef<string>,
  names: ComputedRef<string[]>,
  readonly: () => boolean = () => false,
) {
  const store = useWorkspace()
  const localOrder = ref<string[]>([])
  useViewState(`legend:${key.value}`, { localOrder })
  const items = computed(() => {
    const natural = [...new Set(names.value)].sort((a, b) =>
      collator.compare(legendLabel(a), legendLabel(b)),
    )
    const saved =
      readonly() || !store.project
        ? localOrder.value
        : (store.project.legend_orders?.[key.value] ?? [])
    return [
      ...saved.filter((n) => natural.includes(n)),
      ...natural.filter((n) => !saved.includes(n)),
    ]
  })
  async function save(order: string[]) {
    if (readonly() || !store.project) localOrder.value = order
    else await store.mutate('/presentation', { key: key.value, order }, 'PUT')
  }
  function move(from: number, to: number) {
    if (from < 0 || to < 0 || to >= items.value.length || from === to) return
    const next = [...items.value]
    next.splice(to, 0, next.splice(from, 1)[0]!)
    void save(next)
  }
  return { items, move, reset: () => save([]) }
}
