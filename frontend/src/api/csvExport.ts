import { shallowRef } from 'vue'
import { sessionVersion } from './client'
import { workspaceBlob } from './workspaceDownload'

export type CsvExportRequest = {
  filename: string
  isCurrent?: () => boolean
  load: (labels: Record<string, string>, signal: AbortSignal) => Promise<Blob>
  verify?: () => Promise<unknown>
  archive?: boolean
  samples?: { id: string; name: string; label: string }[]
  labels?: Record<string, string>
  onLabels?: (labels: Record<string, string>) => void
}

export const csvExport = shallowRef<CsvExportRequest>()

export function openCsvExport(request: CsvExportRequest) {
  const session = sessionVersion()
  csvExport.value = {
    ...request,
    isCurrent: () => sessionVersion() === session && (request.isCurrent?.() ?? true),
  }
}

export function openWorkspaceCsv(
  filename: string,
  path: string,
  options: Parameters<typeof workspaceBlob>[1],
  archive = false,
) {
  openCsvExport({
    filename,
    archive,
    isCurrent: options.isCurrent,
    load: (_, signal) => workspaceBlob(path, { ...options, signal }),
  })
}

export function openCsvText(filename: string, text: string, isCurrent?: () => boolean) {
  openCsvExport({
    filename,
    isCurrent,
    load: async () => new Blob([text], { type: 'text/csv;charset=utf-8' }),
  })
}
