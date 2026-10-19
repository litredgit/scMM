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
  molecule_layers: string[]
  sample_field: string
  samples: string[]
  condition_fields: string[]
  condition_values: Record<string, string[]>
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
  candidate_groups?: {
    label: string
    feature_id: string
    formula: string
    adduct: string
    rows: Record<string, unknown>[]
  }[]
  candidate_group_total?: number
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
  chart_view?: Partial<LipidChartView>
  chart_filters?: Record<string, unknown>
  network_parameters?: Record<string, unknown>
  total_features: number
}

export interface LipidChartView {
  classification_level: string
  graph: string
  scope: string
  sign: string
  node_limit: number
  search: string
  category: string
  focus: string
}
export interface LipidNode {
  id: string
  feature_id: string
  mz: number
  label: string
  classification: string
  review?: string
  features?: string[]
}
export interface LipidEdge {
  source: string
  target: string
  sample: string
  rho_all: number
  rho_joint: number | null
  joint_cells: number
  joint_fraction: number
  sign: string
  relation_types: string[]
}
export interface LipidCharts {
  options: LipidChartView
  pie: {
    level: string
    denominator: number
    candidate_mode: string
    filters: Record<string, unknown>
    counts: { classification: string; count: number }[]
  }
  network: null | {
    kind: string
    layer: string
    method: string
    scope: string
    scopes: string[]
    nodes: LipidNode[]
    edges: LipidEdge[]
    total_nodes: number
    truncated: boolean
    molecule_nodes: LipidNode[]
    undetermined_features: string[]
    parameters: Record<string, unknown>
  }
  evidence?: Record<string, unknown>[]
}
