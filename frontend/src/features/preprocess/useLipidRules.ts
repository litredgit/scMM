import { computed, ref, watch, type Ref } from 'vue'
import type { useWorkspace } from '../../stores/workspace'
import type { LipidInfo, LipidRules } from './lipids'

// Owns only rule drafts/presets. Version/query lifecycle remains with useLipidPanel.
export function useLipidRules(
  store: ReturnType<typeof useWorkspace>,
  info: Ref<LipidInfo | undefined>,
  version: () => string,
  loadResults: () => Promise<boolean>,
  limit: number,
) {
  const rules = ref<LipidRules>({ schema_version: 1, name: '', rules: [] })
  const imported = ref(false)
  const preset = ref('')
  const presetName = ref('')
  const ruleOffset = ref(0)
  watch(rules, () => (ruleOffset.value = 0))
  const rulesTable = computed(() => ({
    columns: ['kind', 'level', 'value', 'polarity', 'adduct', 'score'],
    rows: rules.value.rules.slice(ruleOffset.value, ruleOffset.value + limit),
    total: rules.value.rules.length,
  }))
  async function importFile(event: Event) {
    const file = (event.target as HTMLInputElement).files?.[0]
    if (!file) return
    if (file.size > 5_000_000) {
      store.error = '规则文件超过 5 MB。'
      return
    }
    const value = await store.inspect<LipidRules>('/lipids/rules/import', {
      content: await file.text(),
      format: file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'json',
    })
    if (value) {
      rules.value = value
      imported.value = true
      store.notice = '规则已校验，可保存预设或应用排序。'
    }
  }
  function choosePreset() {
    const value = info.value?.presets[preset.value]
    if (value) {
      rules.value = JSON.parse(JSON.stringify(value))
      imported.value = true
    }
  }
  async function savePreset() {
    const value = await store.command<Record<string, LipidRules>>('/lipids/presets', {
      name: presetName.value,
      rules: rules.value,
    })
    if (value && info.value) {
      info.value.presets = value
      store.notice = '规则已保存为预设。'
    }
  }
  async function applyRules() {
    const value = await store.mutate(
      '/lipids/rules/apply',
      { version: version(), rules: rules.value },
      'POST',
      '',
    )
    if (value) {
      imported.value = false
      if (await loadResults()) store.notice = '排序已更新，全部候选仍保留。'
    }
  }
  function template() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify({ schema_version: 1, name: '', rules: [] }, null, 2)], {
        type: 'application/json',
      }),
    )
    const link = document.createElement('a')
    link.href = url
    link.download = 'lipid-rules-template.json'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return {
    rules,
    imported,
    preset,
    presetName,
    ruleOffset,
    rulesTable,
    importFile,
    choosePreset,
    savePreset,
    applyRules,
    template,
  }
}
