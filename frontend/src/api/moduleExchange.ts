import type { ModuleKey } from '../features/modules/modules'

export interface ModuleStatus {
  module: ModuleKey
  protocol_version: number
  quantitation_available: boolean
  feature_only: boolean
  observations: number
  features: number
  observation_kind: 'cell' | 'sample'
  imports: string[]
  exports: string[]
  has_catalogue: boolean
  source: string
  notice: string
}

export async function base64File(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  const chunks: string[] = []
  for (let offset = 0; offset < bytes.length; offset += 0x8000)
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)))
  return btoa(chunks.join(''))
}
