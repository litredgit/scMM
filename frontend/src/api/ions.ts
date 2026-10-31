import type { DataTable } from './types'
export const ionPath = (action: string) => `/ions/${action}`
export type IonView = {
  id: string
  root_id: string
  level: string
  variable_kind: string
  cell_ids: string[]
  variable_ids?: string[]
  feature_ids: string[]
}
export type IonBranch = { id: string; view_id: string; cells: number; variables: number }
export type IonTask = {
  id: string
  status: string
  collectible: boolean
  collected: boolean
  reason: string | null
}
export type IonInfo = {
  initialized: boolean
  catalog_revision: number
  active_branch_id: string | null
  roots: { id: string }[]
  views: IonView[]
  branches: IonBranch[]
  versions: { id: string; root_id: string; groups: number; relations: number; complete: boolean }[]
  annotation_versions: string[]
  tasks: IonTask[]
  species: { id: string; polarity: string }[]
}
export type IonTable = { total: number; offset: number; table: DataTable }
