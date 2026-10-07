/**
 * 极简 ZIP 写入器（无第三方依赖）。
 *
 * 只服务于 C-06 B1 的诊断包：条目少、一次性生成、不需要目录树。
 * 压缩走 `node:zlib` 的 deflateRaw，压缩后不划算的条目退回 stored，
 * 两种方法都可被标准解压器与 `unzip -l` 读取。
 */

import { deflateRawSync } from 'node:zlib'

const LOCAL_HEADER = 0x04034b50
const CENTRAL_HEADER = 0x02014b50
const END_OF_CENTRAL = 0x06054b50
/** 位 11：文件名为 UTF-8。 */
const FLAG_UTF8 = 0x0800
const METHOD_STORE = 0
const METHOD_DEFLATE = 8

export interface ZipEntry {
  /** 归档内路径，使用 `/` 分隔。 */
  readonly name: string
  readonly data: Uint8Array | string
}

const CRC_TABLE = ((): Uint32Array => {
  const table = new Uint32Array(256)
  for (let index = 0; index < 256; index += 1) {
    let value = index
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) === 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    }
    table[index] = value >>> 0
  }
  return table
})()

/** 标准 CRC-32（IEEE 802.3），ZIP 强制要求。 */
export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of data) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

/** 定长 DOS 时间/日期：诊断包无需真实时间戳，固定值保证输出可复现。 */
const DOS_TIME = 0
const DOS_DATE = 0x0021

interface PreparedEntry {
  readonly nameBytes: Buffer
  readonly body: Buffer
  readonly method: number
  readonly crc: number
  readonly offset: number
}

export function createZip(entries: readonly ZipEntry[]): Uint8Array {
  const prepared: PreparedEntry[] = []
  const chunks: Buffer[] = []
  let offset = 0

  for (const entry of entries) {
    const raw = Buffer.isBuffer(entry.data)
      ? entry.data
      : Buffer.from(typeof entry.data === 'string' ? entry.data : Buffer.from(entry.data))
    const deflated = raw.length > 0 ? deflateRawSync(raw, { level: 6 }) : Buffer.alloc(0)
    const useDeflate = deflated.length < raw.length
    const nameBytes = Buffer.from(entry.name, 'utf8')
    const body = useDeflate ? deflated : raw
    prepared.push({
      nameBytes,
      body,
      method: useDeflate ? METHOD_DEFLATE : METHOD_STORE,
      crc: crc32(raw),
      offset,
    })
    offset += 30 + nameBytes.length + body.length
  }

  for (const item of prepared) {
    const header = Buffer.alloc(30)
    header.writeUInt32LE(LOCAL_HEADER, 0)
    header.writeUInt16LE(20, 4)          // version needed
    header.writeUInt16LE(FLAG_UTF8, 6)
    header.writeUInt16LE(item.method, 8)
    header.writeUInt16LE(DOS_TIME, 10)
    header.writeUInt16LE(DOS_DATE, 12)
    header.writeUInt32LE(item.crc, 14)
    header.writeUInt32LE(item.body.length, 18)
    header.writeUInt32LE(item.body.length, 22)
    header.writeUInt16LE(item.nameBytes.length, 26)
    header.writeUInt16LE(0, 28)          // extra length
    chunks.push(header, item.nameBytes, item.body)
  }

  const centralChunks: Buffer[] = []
  let centralSize = 0
  for (const item of prepared) {
    const record = Buffer.alloc(46)
    record.writeUInt32LE(CENTRAL_HEADER, 0)
    record.writeUInt16LE(20, 4)          // version made by
    record.writeUInt16LE(20, 6)          // version needed
    record.writeUInt16LE(FLAG_UTF8, 8)
    record.writeUInt16LE(item.method, 10)
    record.writeUInt16LE(DOS_TIME, 12)
    record.writeUInt16LE(DOS_DATE, 14)
    record.writeUInt32LE(item.crc, 16)
    record.writeUInt32LE(item.body.length, 20)
    record.writeUInt32LE(item.body.length, 24)
    record.writeUInt16LE(item.nameBytes.length, 28)
    record.writeUInt16LE(0, 30)          // extra
    record.writeUInt16LE(0, 32)          // comment
    record.writeUInt16LE(0, 34)          // disk number
    record.writeUInt16LE(0, 36)          // internal attrs
    record.writeUInt32LE(0, 38)          // external attrs
    record.writeUInt32LE(item.offset, 42)
    centralChunks.push(record, item.nameBytes)
    centralSize += 46 + item.nameBytes.length
  }

  const end = Buffer.alloc(22)
  end.writeUInt32LE(END_OF_CENTRAL, 0)
  end.writeUInt16LE(0, 4)
  end.writeUInt16LE(0, 6)
  end.writeUInt16LE(prepared.length, 8)
  end.writeUInt16LE(prepared.length, 10)
  end.writeUInt32LE(centralSize, 12)
  end.writeUInt32LE(offset, 16)
  end.writeUInt16LE(0, 20)                // comment length

  return new Uint8Array(Buffer.concat([...chunks, ...centralChunks, end]))
}
