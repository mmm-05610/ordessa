const BACKWARD_READ_BYTES = 64 * 1024

/**
 * Yield the lines of an open file handle newest-first without loading it, in backward 64k
 * chunks. Each yield is `{ line, offset, chunkEnd }`: the raw line bytes (no trailing `\n`),
 * the byte offset the line starts at, and the end offset of the chunk being scanned (the
 * cursor value the chunk was read back from, for callers whose stop condition depends on
 * how far back the scan has reached). Breaking out of the loop stops the scan; the caller
 * keeps owning the handle.
 */
export async function* scanLinesBackward(handle, { from }) {
  let cursor = from
  let carry = Buffer.alloc(0)
  while (cursor > 0) {
    const start = Math.max(0, cursor - BACKWARD_READ_BYTES)
    const chunk = Buffer.allocUnsafe(cursor - start)
    const { bytesRead } = await handle.read(chunk, 0, chunk.length, start)
    const data = carry.length > 0
      ? Buffer.concat([chunk.subarray(0, bytesRead), carry])
      : chunk.subarray(0, bytesRead)

    let lineEnd = data.length
    for (let index = data.length - 1; index >= 0; index -= 1) {
      if (data[index] !== 0x0a) continue
      const lineStart = index + 1
      if (lineStart < lineEnd) yield { line: data.subarray(lineStart, lineEnd), offset: start + lineStart, chunkEnd: cursor }
      lineEnd = index
    }

    if (start === 0) {
      if (lineEnd > 0) yield { line: data.subarray(0, lineEnd), offset: 0, chunkEnd: cursor }
      cursor = 0
    } else {
      carry = lineEnd > 0 ? Buffer.from(data.subarray(0, lineEnd)) : Buffer.alloc(0)
      cursor = start
    }
  }
}
