export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Insert PNG pHYs using the requested physical DPI; preserve all image samples. */
export async function pngWithDpi(blob: Blob, dpi: number) {
  const source = new Uint8Array(await blob.arrayBuffer())
  const chunk = new Uint8Array(21)
  const view = new DataView(chunk.buffer)
  view.setUint32(0, 9)
  chunk.set([112, 72, 89, 115], 4)
  view.setUint32(8, Math.round(dpi / 0.0254))
  view.setUint32(12, Math.round(dpi / 0.0254))
  chunk[16] = 1
  let crc = 0xffffffff
  for (const byte of chunk.slice(4, 17)) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
  }
  view.setUint32(17, (crc ^ 0xffffffff) >>> 0)
  const parts: BlobPart[] = [source.slice(0, 33), chunk]
  let offset = 33
  while (offset < source.length) {
    const length = new DataView(source.buffer, source.byteOffset + offset).getUint32(0) + 12
    if (String.fromCharCode(...source.slice(offset + 4, offset + 8)) !== 'pHYs')
      parts.push(source.slice(offset, offset + length))
    offset += length
  }
  return new Blob(parts, { type: 'image/png' })
}
