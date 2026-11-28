import { afterEach, describe, expect, it, vi } from 'vitest'
import { csvOffsets, csvRecords } from '../src/api/csvPreview'
import { operationDetails, operationValue } from '../src/api/operation'
import { serialPolling } from '../src/api/polling'
import { isMassSpectrum, spectrumPresentation } from '../src/components/spectrumPresentation'
import { guideForPage } from '../src/features/documentation/documentation'
import { BEFORE_MAINTENANCE } from '../src/api/maintenance'
import { useReadScope } from '../src/api/readScope'
import type { Figure } from '../src/api/types'

vi.hoisted(() => vi.stubGlobal('window', new EventTarget()))

describe('workbench contracts', () => {
  afterEach(() => vi.useRealTimers())

  it('ignores a late poll after stopping', async () => {
    vi.useFakeTimers()
    let finish!: () => void
    const published: string[] = []
    const action = vi.fn(async (current: () => boolean) => {
      await new Promise<void>((resolve) => {
        finish = resolve
      })
      if (current()) published.push('ready')
    })
    const polling = serialPolling(action, 100, vi.fn())
    polling.start()
    await Promise.resolve()
    polling.stop()
    finish()
    await vi.runAllTimersAsync()
    expect(action).toHaveBeenCalledTimes(1)
    expect(published).toEqual([])
  })

  it('indexes UTF-8 CSV with a quoted line break as a single record', async () => {
    const text = 'id,备注\r\n1,"第一行\n第二行"\r\n'
    const blob = new Blob([text])
    expect(csvRecords(text)).toEqual([
      ['id', '备注'],
      ['1', '第一行\n第二行'],
    ])
    expect(await csvOffsets(blob, 10, new AbortController().signal)).toEqual([
      0,
      new Blob(['id,备注\r\n']).size,
      blob.size,
    ])
  })

  it('distinguishes preview from a committed analysis operation', () => {
    expect(
      operationDetails('/analysis/operation', { operation: 'normalize', preview: true }),
    ).toEqual({
      label: '归一化',
      phase: 'reading',
    })
    expect(operationValue({ status: 'succeeded', value: 0 })).toBe(0)
  })

  it('invalidates a read when a newer read begins for the same input', () => {
    const warnings = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const scope = useReadScope(() => 'same')
      const first = scope.begin()
      const second = scope.begin()
      expect(first()).toBe(false)
      expect(second()).toBe(true)
      scope.invalidate()
      expect(second()).toBe(false)
    } finally {
      warnings.mockRestore()
    }
  })

  it('opens the step-specific guide and uses the shared maintenance event', () => {
    expect(guideForPage('/raw')).toEqual({ file: 'docs/extraction.md', anchor: '预览与应用参数' })
    expect(guideForPage('/unknown')).toEqual({ file: 'docs/README.md' })
    expect(BEFORE_MAINTENANCE).toBe('scmm-before-maintenance')
  })

  it('recognizes an m/z spectrum and preserves its export table', () => {
    const figure: Figure = {
      layout: {
        xaxis: { title: { text: 'm/z' } },
        meta: { export_tables: { peaks: 'mz,intensity\n1,2' } },
      },
      data: [{ x: [1], y: [2], type: 'scatter' }],
    }
    expect(isMassSpectrum(figure)).toBe(true)
    const shown = spectrumPresentation(
      figure,
      {
        relative: false,
        labels: false,
        decimals: 4,
        threshold: 0,
        interaction: 'zoom',
      },
      900,
    )
    expect(shown.layout.meta).toMatchObject({ export_tables: { peaks: 'mz,intensity\n1,2' } })
  })
})

describe('view draft lifecycle', () => {
  it('keeps evicted values and never replays a pending value over a new edit or scope', async () => {
    const { createRenderer, nextTick, ref, watch } = await import('vue')
    const draft = await import('../src/api/viewState')
    const { captureViews, clearPendingViews, restoreViews, useViewState } = draft
    const restorationFlags: boolean[] = []
    clearPendingViews()
    const renderer = createRenderer({
      createComment: () => ({}),
      createElement: () => ({}),
      createText: () => ({}),
      insert() {},
      nextSibling: () => null,
      parentNode: () => null,
      patchProp() {},
      remove() {},
      setElementText() {},
      setText() {},
    })
    const mount = (initial: string) => {
      const field = ref(initial)
      const app = renderer.createApp({
        setup() {
          const initialize = useViewState('panel', { field })
          watch(
            () => initial,
            () => initialize(() => (field.value = 'initialized')),
            { immediate: true, flush: 'post' },
          )
          watch(
            field,
            () => {
              if (field.value === 'edited') restorationFlags.push(draft.restoringViews)
            },
            { flush: 'post' },
          )
          return () => null
        },
      })
      app.mount({})
      return { field, unmount: () => app.unmount() }
    }
    const first = mount('default')
    await nextTick()
    first.field.value = 'edited'
    await nextTick()
    first.unmount()
    expect(captureViews().panel).toEqual({ field: 'edited' })
    const returned = mount('default')
    await nextTick()
    expect(returned.field.value).toEqual('edited')
    await nextTick()
    expect(restorationFlags).toEqual([false, true])
    clearPendingViews()
    returned.unmount()
    expect(captureViews().panel).toBeUndefined()
    await restoreViews({ panel: { field: 'pending' } })
    const incoming = mount('default')
    incoming.field.value = 'new edit'
    await nextTick()
    expect(incoming.field.value).toEqual('new edit')
    incoming.unmount()
    clearPendingViews()
  })
})
