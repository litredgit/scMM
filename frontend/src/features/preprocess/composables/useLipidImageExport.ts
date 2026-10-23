import { useWorkspace } from '../../../stores/workspace'
import { workspaceBlob, saveBlob } from '../../../api/workspaceDownload'
import { ApiError } from '../../../api/client'
import { pngWithDpi } from '../../../components/plotExport'

type Options = {
  svg(kind: 'pie' | 'network'): SVGSVGElement | null | undefined
  width(): number
  dpi(): number
  font(): number
  version(): string
}
/** Own the whole image export; display settings are frozen before any asynchronous work. */
export function useLipidImageExport(options: Options) {
  const store = useWorkspace()
  async function image(kind: 'pie' | 'network', format: 'svg' | 'png' | 'pdf') {
    if (!store.current) return
    const snapshot = store.current
    const source = options.version()
    return store.run(
      async (scope) => {
        const svg = options.svg(kind)
        if (!svg) return
        const width = options.width(),
          dpi = options.dpi(),
          font = options.font()
        const isCurrent = () =>
          scope.isCurrent() &&
          store.current?.workspace_id === snapshot.workspace_id &&
          store.current?.revision === snapshot.revision &&
          source === options.version()
        const check = () => {
          if (!isCurrent())
            throw new ApiError('图形来源已改变，旧导出已丢弃。', 'operation_stale', 409)
        }
        const clone = svg.cloneNode(true) as SVGSVGElement
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        clone.setAttribute('width', `${width}mm`)
        const height = (width * svg.viewBox.baseVal.height) / svg.viewBox.baseVal.width
        clone.setAttribute('height', `${height}mm`)
        const size = (font * svg.viewBox.baseVal.width) / ((width * 72) / 25.4)
        for (const text of clone.querySelectorAll('text')) {
          text.setAttribute('font-size', String(size))
          text.setAttribute('font-family', 'Arial, Helvetica, sans-serif')
        }
        const content = new XMLSerializer().serializeToString(clone)
        const blob = new Blob([content], { type: 'image/svg+xml;charset=utf-8' })
        const name = `lipid-${kind}-${source}`
        if (format === 'svg') {
          check()
          return saveBlob(blob, `${name}.svg`)
        }
        if (format === 'pdf') {
          const result = await workspaceBlob('/figures/pdf', {
            workspace: snapshot.workspace_id,
            method: 'POST',
            body: { svg: content, width_mm: width, height_mm: height },
            isCurrent,
          })
          return saveBlob(result, `${name}.pdf`)
        }
        if (width < 20 || width > 600 || dpi < 72 || dpi > 2400 || font < 4.5 || font > 24)
          throw new Error('请检查尺寸、字号和 DPI。')
        if ((((width / 25.4) * dpi * height) / 25.4) * dpi > 60000000)
          throw new Error('请减小成图尺寸或 DPI。')
        const url = URL.createObjectURL(blob)
        try {
          const img = new Image()
          img.src = url
          await img.decode()
          check()
          const canvas = document.createElement('canvas')
          canvas.width = Math.round((width / 25.4) * dpi)
          canvas.height = Math.round((height / 25.4) * dpi)
          const ctx = canvas.getContext('2d')!
          ctx.fillStyle = 'white'
          ctx.fillRect(0, 0, canvas.width, canvas.height)
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
          const value = await new Promise<Blob>((resolve, reject) =>
            canvas.toBlob((v) => (v ? resolve(v) : reject(new Error('PNG 导出失败'))), 'image/png'),
          )
          const result = await pngWithDpi(value, dpi)
          check()
          saveBlob(result, `${name}.png`)
        } finally {
          URL.revokeObjectURL(url)
        }
      },
      '',
      { label: '导出脂质图形', phase: 'downloading' },
    )
  }
  return { image }
}
