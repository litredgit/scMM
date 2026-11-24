import { ref, shallowRef } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { workspaceBlob } from '../../../api/workspaceDownload'
import { pngWithDpi, type ImageFormat } from '../../../components/plotExport'

type Kind = 'pie' | 'network'

export function useLipidImageExport(
  svgElement: (kind: Kind) => SVGSVGElement | null | undefined,
  version: () => string,
) {
  const store = useWorkspace()
  const svg = shallowRef<SVGSVGElement>()
  const source = shallowRef<{ workspace: string; revision: number; version: string }>()
  const filename = ref('')
  const width = ref(89)
  const height = ref<number | ''>('')
  const dpi = ref(300)
  const font = ref(7)
  const family = ref('Arial, Helvetica, sans-serif')
  const transparent = ref(false)

  function capture(kind: Kind) {
    const current = store.current
    const element = svgElement(kind)
    if (!current || !element) return false
    svg.value = element.cloneNode(true) as SVGSVGElement
    source.value = {
      workspace: current.workspace_id,
      revision: current.revision,
      version: version(),
    }
    filename.value = `lipid-${kind}-${version()}`
    return true
  }
  function isCurrent() {
    return (
      !!source.value &&
      store.current?.workspace_id === source.value.workspace &&
      store.current?.revision === source.value.revision &&
      version() === source.value.version
    )
  }
  async function render(format: ImageFormat, signal: AbortSignal) {
    if (!svg.value || !source.value) throw new Error('图形尚未渲染。')
    const original = svg.value
    const dimensions = original.viewBox.baseVal
    const w = width.value
    const h = height.value || (w * dimensions.height) / dimensions.width
    const density = dpi.value
    const size = font.value
    const clear = transparent.value && format !== 'pdf'
    if (
      ![w, h, density, size].every(Number.isFinite) ||
      w < 20 ||
      w > 600 ||
      h < 20 ||
      h > 600 ||
      density < 72 ||
      density > 2400 ||
      size < 4.5 ||
      size > 24
    )
      throw new Error('请检查尺寸、字号和 DPI。')
    const clone = original.cloneNode(true) as SVGSVGElement
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.setAttribute('width', `${w}mm`)
    clone.setAttribute('height', `${h}mm`)
    if (!clear) {
      const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
      background.setAttribute('width', '100%')
      background.setAttribute('height', '100%')
      background.setAttribute('fill', 'white')
      clone.prepend(background)
    }
    const svgFontSize = (size * dimensions.width) / ((w * 72) / 25.4)
    for (const text of clone.querySelectorAll('text')) {
      text.setAttribute('font-size', String(svgFontSize))
      text.setAttribute('font-family', family.value)
    }
    const content = new XMLSerializer().serializeToString(clone)
    const rendered = new Blob([content], { type: 'image/svg+xml;charset=utf-8' })
    if (format === 'svg') return { file: rendered }
    if (format === 'pdf') {
      const file = await workspaceBlob('/figures/pdf', {
        workspace: source.value.workspace,
        method: 'POST',
        body: { svg: content, width_mm: w, height_mm: h },
        signal,
        isCurrent,
      })
      return { file, preview: rendered }
    }
    const pixelsWide = Math.round((w / 25.4) * density)
    const pixelsHigh = Math.round((h / 25.4) * density)
    if (pixelsWide * pixelsHigh > 60_000_000) throw new Error('请减小成图尺寸或 DPI。')
    const url = URL.createObjectURL(rendered)
    try {
      const img = new Image()
      img.src = url
      await img.decode()
      signal.throwIfAborted()
      const canvas = document.createElement('canvas')
      canvas.width = pixelsWide
      canvas.height = pixelsHigh
      const context = canvas.getContext('2d')
      if (!context) throw new Error('浏览器无法生成 PNG。')
      context.drawImage(img, 0, 0, pixelsWide, pixelsHigh)
      const png = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob(
          (value) => (value ? resolve(value) : reject(new Error('PNG 导出失败'))),
          'image/png',
        ),
      )
      return { file: await pngWithDpi(png, density) }
    } finally {
      URL.revokeObjectURL(url)
    }
  }
  return { capture, isCurrent, render, filename, width, height, dpi, font, family, transparent }
}
