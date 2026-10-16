import type { DataTable } from '../../api/types'

export interface LipidRules {
  schema_version: number
  name: string
  rules: Record<string, unknown>[]
}
export interface LipidInfo {
  database: {
    directory: string
    files: { filename: string; bytes: number }[]
    available: boolean
    error?: string
  }
  adducts: Record<string, { polarity: string }>
  presets: Record<string, LipidRules>
  active: string
  layers: string[]
  default_layer: string
  resolution: number
  versions: {
    id: string
    label: string
    created_at: string
    valid: boolean
    candidates: number
    isotope_matches: number
  }[]
}
export interface LipidResults {
  version: string
  parameters: Record<string, unknown>
  rules: LipidRules
  database: { filename: string; sha256: string; records: number }
  intensity_layer: string
  features: { id: string; mz: number; candidates: number; isotope: boolean; reviewed: boolean }[]
  candidates: DataTable
  isotopes: DataTable
  selected: Record<string, string[]>
  suggested: string[]
  diagnostics: Record<string, unknown>[]
  classification: Record<string, string[]>
  classification_tree: Record<string, string>[]
  total_features: number
}
