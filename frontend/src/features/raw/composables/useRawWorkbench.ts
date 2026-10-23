import { ref } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { useAuth } from '../../../stores/auth'
import { useViewState } from '../../../api/viewState'
import { useRawParameters } from './useRawParameters'
import { useRawSpectra } from './useRawSpectra'
import { useCellPreview } from './useCellPreview'

/** Assemble owners; keep the existing raw draft keys and refs for maintenance/save restoration. */
export function useRawWorkbench() {
  const store = useWorkspace(),
    auth = useAuth(),
    sample = ref('')
  const form = useRawParameters(sample)
  const spectra = useRawSpectra({
    sample,
    parameters: () => form.parameters.value,
    assignParameters: form.assignParams,
  })
  const preview = useCellPreview({
    sample,
    parameters: form.valueParams,
    invalidate() {
      delete spectra.plots.value.cells
    },
    collected(value) {
      form.assignParams(value.parameters)
      spectra.plots.value.cells = value
      spectra.kind.value = 'cells'
    },
  })
  form.connect({
    reset() {
      spectra.reset()
      preview.reset()
    },
    edited: preview.edited,
    assigned(value) {
      spectra.refs.value = String(value.reference_mz || value.ref_mz || '')
    },
  })
  const {
    opened,
    summary,
    kind,
    ms,
    scan,
    rtMin,
    rtMax,
    mzMin,
    mzMax,
    refs,
    ppm,
    fast,
    normalize,
    bins,
    plots,
  } = spectra
  const { jobNote, cellCount } = preview
  const {
    parameters,
    effectiveParameters,
    applicationScope,
    strategy,
    mergePpm,
    autoRanges,
    preset,
  } = form
  useViewState('raw', {
    sample,
    opened,
    summary,
    parameters,
    kind,
    ms,
    scan,
    rtMin,
    rtMax,
    mzMin,
    mzMax,
    refs,
    ppm,
    fast,
    normalize,
    bins,
    plots,
    jobNote,
    cellCount,
    effectiveParameters,
    applicationScope,
    strategy,
    mergePpm,
    autoRanges,
    preset,
  })
  const { connect: _connect, assignParams: _assign, valueParams: _values, ...formState } = form
  const { reset: _reset, ...spectraState } = spectra
  return {
    store,
    auth,
    sample,
    ...formState,
    ...spectraState,
    job: preview.job,
    jobNote,
    cellCount,
    startPreview: preview.startPreview,
    edited: form.edited,
  }
}
