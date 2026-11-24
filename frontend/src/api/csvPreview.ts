/** Index record boundaries on bytes, preserving quoted newlines and UTF-8 content. */
export async function csvOffsets(blob: Blob, limit: number, signal: AbortSignal) {
  const starts = [0]
  const reader = blob.stream().getReader()
  let quoted = false
  let previousCR = false
  let position = 0
  try {
    for (;;) {
      signal.throwIfAborted()
      const { value, done } = await reader.read()
      if (done) break
      for (const byte of value) {
        position++
        if (previousCR && byte === 10) {
          starts[starts.length - 1] = position
          previousCR = false
          continue
        }
        previousCR = false
        if (starts.length > limit) return starts
        if (byte === 34) quoted = !quoted
        if (!quoted && (byte === 10 || byte === 13)) {
          starts.push(position)
          previousCR = byte === 13
        }
      }
    }
  } finally {
    await reader.cancel()
  }
  if (quoted) throw new Error('CSV 包含未闭合的引号。')
  if (starts.at(-1) !== blob.size) starts.push(blob.size)
  return starts
}

export function csvRecords(text: string) {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const char = text[i]!
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"'
        i++
      } else {
        quoted = !quoted
      }
    } else if (!quoted && char === ',') {
      row.push(field)
      field = ''
    } else if (!quoted && (char === '\r' || char === '\n')) {
      if (char === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += char
    }
  }
  if (row.length || field.length || (text.length && !/[\r\n]$/.test(text))) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

type Table = { name: string; load: () => Promise<Blob> }

/** scMM writes ordinary ZIP archives with stored or deflated UTF-8 CSV members. */
export async function zipCsvTables(blob: Blob): Promise<Table[]> {
  const trailer = new DataView(await blob.slice(Math.max(0, blob.size - 65_557)).arrayBuffer())
  let end = trailer.byteLength - 22
  for (; end >= 0; end--) {
    if (
      trailer.getUint32(end, true) === 0x06054b50 &&
      end + 22 + trailer.getUint16(end + 20, true) === trailer.byteLength
    )
      break
  }
  if (end < 0) throw new Error('无法读取 ZIP 的表目录。')
  const start = trailer.getUint32(end + 16, true)
  const length = trailer.getUint32(end + 12, true)
  if (start + length > blob.size) throw new Error('ZIP 表目录范围无效。')
  const directory = new DataView(await blob.slice(start, start + length).arrayBuffer())
  const result: Table[] = []
  for (let i = 0; i < directory.byteLength;) {
    if (i + 46 > directory.byteLength || directory.getUint32(i, true) !== 0x02014b50)
      throw new Error('ZIP 表目录格式无效。')
    const size = directory.getUint32(i + 20, true)
    const header = directory.getUint32(i + 42, true)
    const method = directory.getUint16(i + 10, true)
    const nameSize = directory.getUint16(i + 28, true)
    const name = new TextDecoder().decode(new Uint8Array(directory.buffer, i + 46, nameSize))
    if (/\.csv$/i.test(name)) {
      result.push({
        name,
        load: async () => {
          const entry = new DataView(await blob.slice(header, header + 30).arrayBuffer())
          if (entry.byteLength < 30 || entry.getUint32(0, true) !== 0x04034b50)
            throw new Error('CSV 表头无法读取。')
          const offset = header + 30 + entry.getUint16(26, true) + entry.getUint16(28, true)
          if (offset + size > blob.size) throw new Error('CSV 表范围无效。')
          const payload = blob.slice(offset, offset + size)
          if (method === 0) return payload
          if (method !== 8) throw new Error('CSV 表的 ZIP 压缩格式无法预览。')
          return new Response(
            payload.stream().pipeThrough(new DecompressionStream('deflate-raw')),
          ).blob()
        },
      })
    }
    i += 46 + nameSize + directory.getUint16(i + 30, true) + directory.getUint16(i + 32, true)
  }
  return result
}
