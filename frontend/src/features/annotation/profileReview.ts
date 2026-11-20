export interface ProfileCandidate {
  candidate_id: string
  feature_id: string
  name: string
  adduct: string
}

export interface ProfileReview {
  id?: string
  native_id: string
  scan_index: number
  source: string
  version: string
  rt_seconds: number
  candidates: (ProfileCandidate & { mono_mz: number })[]
  status: 'compared' | 'unresolved'
  reason?: string
  isotope_order: number
  separation_da: number
  fwhm_da: number | null
  fwhm_source: 'entered' | 'same_scan_parent'
  offset_ppm: number
  parent_height?: number
  competing_height?: number
  competing_height_sensitivity?: [number, number]
  parent_only_relative_rmse?: number
  mixed_relative_rmse?: number
  profile?: {
    mz: number[]
    observed: number[]
    parent_only: number[]
    mixed: number[]
    residual: number[]
    region: ('parent' | 'overlap')[]
  }
}
