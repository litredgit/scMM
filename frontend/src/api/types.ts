export interface Sample {
  id: string
  name: string
  path: string
  storage: string
  group: string
  subject: string
  batch: string
  parameters?: Record<string, unknown> | null
  result_only?: boolean
  metadata_unresolved?: string[]
}

export interface DatasetSummary {
  id: string
  revision: number
  cells: number
  features: number
  observation_columns: string[]
  source: string
  quantitation_available?: boolean
  observation_kind?: 'cell' | 'sample'
}

export interface ProjectView {
  path: string
  manifest: {
    id: string
    name: string
    description: string
    revision: number
    saved_at: string
    samples: Sample[]
    parameters: Record<string, unknown>
    feature_strategy: string
    [key: string]: unknown
  }
  presentation: Record<string, string>
  legend_orders: Record<string, string[]>
  unsaved: boolean
  dataset: DatasetSummary | null
  annotation?: {
    sources: AnnotationSource[]
    default_source: string
    statistics: { branch_id: string; view_id: string; level: string } | null
  }
}

export interface AnnotationSource {
  id: string
  identity: string
  label: string
  features: number
  quantitation_available: boolean
}

export interface WorkspaceView {
  workspace_id: string
  revision: number
  project: ProjectView | null
}

export interface SavedProject {
  created_at?: string | null
  description: string
  path: string
  name: string
  saved_at: string
  samples: number
  data_state?: 'configuration' | 'saved' | 'unavailable'
  cells?: number | null
  features?: number | null
}
export interface Root {
  label: string
  path: string
}
export interface Parameter {
  name: string
  default: unknown
  help: string
}
export interface Configuration {
  milestone: string
  storage: Root[]
  results: Root[]
  project_root: string
  processing: Parameter[]
  analysis: Parameter[]
  workspace_idle_seconds: number
  enabled_plugins: string[]
  methods: PluginMethod[]
}
export type PluginKind =
  | 'cell_detection'
  | 'cell_extraction'
  | 'annotation'
  | 'preprocessing'
  | 'reduction'
  | 'clustering'
  | 'statistics'
export type PluginValue = number | string | boolean | null
export interface PluginParameter {
  key: string
  label: string
  kind: 'integer' | 'number' | 'text' | 'boolean' | 'choice' | 'observation'
  default: PluginValue
  minimum: number | null
  maximum: number | null
  help: string
  choices: string[]
}
export interface PluginMethod {
  id: string
  version: string
  label: string
  kind: PluginKind
  parameters: PluginParameter[]
}
export interface FileEntry {
  name: string
  path: string
  directory: boolean
  bytes: number | null
  role?: string
  detail?: string
  internal?: boolean
  project_name?: string | null
  project_path?: string | null
  revision?: number | null
  modified_at?: string | null
  protection?: string
}
export interface Directory {
  root: string
  path: string
  parent: string | null
  entries: FileEntry[]
  total: number
  latest?: FileEntry | null
  context?: Partial<FileEntry> | null
}
export interface Mapping {
  source_key: string
  columns: string[]
  rows: { value: string; sample_id: string }[]
}

export interface DataTable {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
}
export interface Figure {
  data: unknown[]
  layout: Record<string, unknown>
}
export interface QC {
  notes?: string[]
  files: DataTable
  cells: DataTable
  figure: Figure
}
export interface AnalysisInfo {
  token: [string, number]
  layers: string[]
  embeddings: string[]
  embedding_dimensions: Record<string, number>
  embedding_variance: Record<string, number[]>
  feature_columns?: string[]
  observations: Record<string, string[]>
  history: Record<string, unknown>[]
  results: string[]
  method_reports: { id: string; label: string; identity: string }[]
  live_results: string[]
  latent_supported: boolean
  settings: Record<string, unknown>
  legend: string
  figures: string[]
}
export interface Batch {
  stop_requested?: boolean
  stage?: string
  stage_progress?: number | null
  started_at?: string
  updated_at?: string
  finished_at?: string
  current_sample?: string
  path: string
  status: string
  created_at: string
  message: string
  samples: {
    id: string
    name: string
    status: string
    cells?: number
    features?: number
    error?: string
    stage?: string
    progress?: number | null
    reused_preview?: boolean
  }[]
}
export interface Job {
  id: string
  revision: number
  status: string
  message: string
}
