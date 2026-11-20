import type { DataTable } from '../../api/types'

export interface LipidRules {
  schema_version: number
  name: string
  rules: Record<string, unknown>[]
}
export interface LipidInfo {
  quantitation_available?: boolean
  database: {
    directory: string
    files: { filename: string; bytes: number }[]
    available: boolean
    error?: string
    presets?: {
      id: string
      label: string
      available: boolean
      records: number
      source?: string
      ms2_status?: string
      description?: string
    }[]
  }
  adducts: Record<string, { polarity: string }>
  presets: Record<string, LipidRules>
  active: string
  grouping_versions?: string[]
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
    mass_only?: boolean
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
  review_revision?: number
  parameters: Record<string, unknown>
  rules: LipidRules
  database: { filename: string; sha256: string; records: number }
  intensity_layer: string
  features: { id: string; mz: number; candidates: number; isotope: boolean; reviewed: boolean }[]
  candidates: DataTable
  feature_candidates: DataTable
  isotopes: DataTable
  selected: Record<string, string[]>
  annotation_names?: Record<string, string>
  suggested: string[]
  diagnostics: Record<string, unknown>[]
  audit?: Record<string, unknown>[]
  classification: Record<string, string[]>
  classification_tree: Record<string, string>[]
  chart_view?: Partial<LipidChartView>
  chart_filters?: Record<string, unknown>
  network_parameters?: Record<string, unknown>
  total_features: number
}

export function ms2Label(status: unknown): string {
  return (
    (
      {
        not_supplied: 'MS2: Not supplied',
        available: 'MS2: Available in database',
        matched: 'MS2: Matched',
        no_match: 'MS2: No match',
        unavailable: 'MS2: No spectrum in database',
        unknown: 'MS2: Unknown',
        mixed: 'MS2: Mixed (see candidates)',
      } as Record<string, string>
    )[String(status)] ?? 'MS2: Unknown'
  )
}

export interface AnnotationSpectrum {
  spectrum_kind: 'feature_sticks' | 'raw_profile'
  intensity_label: string
  intensity_missing: boolean
  relative_intensity_allowed?: boolean
  intensity_source: {
    layer: string
    aggregation: string
    sample: string
    quantitation_available: boolean
  }
  peaks: {
    feature_id: string
    mz: number
    intensity: number | null
    label: string
    role: 'selected' | 'isotope' | 'adduct' | 'unrelated'
    candidate_ids: string[]
    candidate_count?: number
    candidate_names?: string[]
    reviewed?: boolean
    ms2_status: string
    annotations?: {
      candidate_id: string
      display_name: string
      name: string
      adduct: string
      isotope_order: number
      database_filename?: string
      database_id?: string
      ms2_status: string
      manual_group_assertion?: boolean
    }[]
  }[]
  relations: {
    id: string
    source: string
    target: string
    type: 'isotope' | 'adduct' | 'charge' | 'multimer' | 'neutral_loss' | 'fragment_form'
    review: string
    candidate_ids: string[]
    sample?: string
    name?: string
    adduct?: string
    shared_review?: string
    origin?: string
    left_species?: string
    right_species?: string
    ppm_error?: number
  }[]
  selected_feature_id: string
  linked_feature_ids: string[]
  confirmed_linked_feature_ids?: string[]
  version: string
  review_revision: number
  dataset_token: [string, number]
  database: { filename?: string; label?: string }
  review_conflicts: unknown[]
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
