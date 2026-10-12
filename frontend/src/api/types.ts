export interface Sample {
  id: string
  name: string
  path: string
  storage: string
  group: string
  subject: string
  batch: string
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
  unsaved: boolean
  dataset: DatasetSummary | null
}

export interface WorkspaceView {
  workspace_id: string
  revision: number
  project: ProjectView | null
}

export interface SavedProject {
  path: string
  name: string
  saved_at: string
  samples: number
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
}
export interface FileEntry {
  name: string
  path: string
  directory: boolean
  bytes: number | null
}
export interface Directory {
  root: string
  path: string
  parent: string | null
  entries: FileEntry[]
  total: number
}
export interface Mapping {
  source_key: string
  columns: string[]
  rows: { value: string; sample_id: string }[]
}
